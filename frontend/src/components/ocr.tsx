import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanText } from "lucide-react";
import { api, message } from "../api";
import type { Episode } from "../types";
import { Button } from "./ui/button";
import { ErrorNotice, Modal, Progress, Spinner } from "./shared";

type Options = { top: number; bottom: number; left: number; right: number; fps: 2 | 4; mode: "white" | "gray"; threshold: number; confidence: number };
const defaults: Options = { top: 70, bottom: 100, left: 5, right: 95, fps: 4, mode: "white", threshold: 200, confidence: 65 };
type OcrTask = { id: string; name: string; path: string; status: string; progress: number; index: number; total: number;
  cue_count: number; duration: number; options: Options; error: string | null; warning: string; srt?: string; pause_requested: boolean };
const labels: Record<string, string> = { queued: "En attente", running: "Lecture des images", paused: "En pause", interrupted: "Interrompu",
  error: "À corriger", review: "SRT anglais à relire", published: "Source anglaise prête", cancelled: "Annulé" };
export type OcrTarget = { episode?: Episode; id?: string };
export function useOcrTasks() {
  return useQuery({ queryKey: ["ocr-tasks"], queryFn: () => api<OcrTask[]>("/ocr/tasks"), refetchInterval: 1500 });
}

export function OcrTasks({ open }: { open: (target: OcrTarget) => void }) {
  const query = useOcrTasks();
  if (!query.data?.length) return null;
  return <details className="ocr-history" open>
    <summary><ScanText size={17} /> Extractions OCR ({query.data.length}) <span>Une vidéo traitée à la fois · reprise conservée</span></summary>
    <div className="ocr-history-list">{query.data.map(task => <button key={task.id} onClick={() => open({ id: task.id })}>
      <strong>{task.name}</strong><span>{task.pause_requested ? "Pause demandée" : labels[task.status]} · {task.progress} % · {task.cue_count} répliques</span>
    </button>)}</div>
  </details>;
}

export function OcrDialog({ target, candidates, close, prepared, notify }: {
  target: OcrTarget; candidates: Episode[]; close: () => void;
  prepared: (episode: Episode, track: string) => void; notify: (text: string, error?: boolean) => void;
}) {
  const client = useQueryClient();
  const [createdId, setCreatedId] = useState("");
  const id = target.id || createdId;
  const [options, setOptions] = useState<Options>(defaults);
  const [at, setAt] = useState(Math.min(30, (target.episode?.duration || 60)/2));
  const [bulk, setBulk] = useState(false);
  const [content, setContent] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const query = useQuery({ queryKey: ["ocr-task", id], queryFn: () => api<OcrTask>(`/ocr/tasks/${id}`), enabled: !!id,
    refetchInterval: query => ['queued', 'running'].includes(query.state.data?.status || '') ? 1500 : false });
  const task = query.data;
  useEffect(() => { setContent(task?.srt || ""); setReviewed(false); }, [id, task?.srt]);
  const refresh = () => { void client.invalidateQueries({ queryKey: ["ocr-tasks"] }); void query.refetch(); };
  const sample = useMutation({ mutationFn: (body: { path: string; options: Options; at: number }) =>
    api<{ image: string; text: string; confidence: number; warning: string }>("/ocr/snapshot", body) });
  const create = useMutation({ mutationFn: (paths: string[]) => api<OcrTask[]>("/ocr/tasks", { paths, options }),
    onSuccess: tasks => { setCreatedId(tasks[0].id); void client.invalidateQueries({ queryKey: ["ocr-tasks"] }); },
    onError: error => notify(message(error), true) });
  const action = useMutation({ mutationFn: (name: string) => api(`/ocr/tasks/${id}/${name}`, {}),
    onSuccess: (_, name) => { refresh(); if (name === "delete") close(); }, onError: error => notify(message(error), true) });
  const publish = useMutation({ mutationFn: () => api<{ episode: Episode; track_id: string }>(`/ocr/tasks/${id}/publish`, { content, reviewed }),
    onSuccess: result => { void client.invalidateQueries({ queryKey: ["ocr-tasks"] }); prepared(result.episode, result.track_id); close(); },
    onError: error => notify(message(error), true) });
  const validSample = sample.isSuccess && !!sample.data.text && JSON.stringify(sample.variables.options) === JSON.stringify(options) && sample.variables.at === at;
  const bulkPaths = Array.from(new Set([target.episode?.path || "", ...candidates.map(e => e.path)]));
  const paths = bulk ? bulkPaths : [target.episode?.path || ""];
  function edit(key: keyof Options, value: string) {
    setOptions(previous => ({ ...previous, [key]: key === "mode" ? value : Number(value) }));
  }
  return <Modal open onOpenChange={open => { if (!open) close(); }} wide title="Extraire les sous-titres incrustés"
    description={target.episode?.name || task?.name || "Extraction OCR"}>
    <div className="ocr-body">
      <p className="notice">OCR anglais en local. Aucune image envoyée à un fournisseur. Le texte et les timings devront être vérifiés avant traduction ; l’anglais incrusté reste visible dans la vidéo.</p>
      {!id && target.episode && <>
        <p>Choisissez une image où un dialogue apparaît, puis ajustez le cadre pour entourer uniquement les sous-titres.</p>
        <div className="ocr-fields">
          <label>Image à la seconde<input type="number" min={0} max={Math.max(0, target.episode.duration-.01)} step={1} value={at} onChange={e => setAt(Number(e.target.value))} /></label>
          {([['top', 'Haut (%)'], ['bottom', 'Bas (%)'], ['left', 'Gauche (%)'], ['right', 'Droite (%)']] as const).map(([key, label]) =>
            <label key={key}>{label}<input type="number" min={0} max={100} step={1} value={options[key]} onChange={e => edit(key, e.target.value)} /></label>)}
          <label>Contraste<select value={options.mode} onChange={e => edit('mode', e.target.value)}><option value="white">Texte clair sur contour sombre</option><option value="gray">Image en niveaux de gris</option></select></label>
          {options.mode === 'white' && <label>Seuil du texte clair<input type="number" min={120} max={245} value={options.threshold} onChange={e => edit('threshold', e.target.value)} /></label>}
          <label>Échantillonnage<select value={options.fps} onChange={e => edit('fps', e.target.value)}><option value={4}>4 images/s · pas de 250 ms</option><option value={2}>2 images/s · pas de 500 ms</option></select></label>
          <label>Confiance minimale<input type="number" min={30} max={95} value={options.confidence} onChange={e => edit('confidence', e.target.value)} /></label>
        </div>
        <Button variant="outline" disabled={sample.isPending || !Number.isFinite(at)} onClick={() => sample.mutate({ path: target.episode!.path, options, at })}>
          {sample.isPending ? 'Lecture de l’image…' : 'Tester cette image'}
        </Button>
        {sample.isError && <ErrorNotice error={message(sample.error)} />}
        {sample.data && <div className="ocr-sample">
          <div className="ocr-frame"><img src={sample.data.image} alt="Image de la vidéo pour régler la zone OCR" />
            <div aria-label="Zone de reconnaissance" className="ocr-crop" style={{ top: `${options.top}%`, height: `${Math.max(0, options.bottom-options.top)}%`, left: `${options.left}%`, width: `${Math.max(0, options.right-options.left)}%` }} />
          </div>
          <p>Texte reconnu · score {sample.data.confidence.toFixed(0)}/100 (ce score ne garantit pas la justesse)</p>
          <pre>{sample.data.text || 'Aucun texte suffisamment lisible. Essayez une autre image, une zone plus serrée ou le mode gris.'}</pre>
          {!validSample && <p className="muted">Testez à nouveau après avoir ajusté les réglages.</p>}
        </div>}
        {candidates.length > 1 && <label className="ocr-check"><input type="checkbox" checked={bulk} disabled={bulkPaths.length > 50} onChange={e => setBulk(e.target.checked)} />
          Appliquer ces réglages aux {bulkPaths.length} épisodes de ce scan (cet épisode et les fichiers sans piste texte), sous-dossiers inclus, 50 maximum.
        </label>}
        <p className="muted">Une extraction complète peut prendre plusieurs minutes ou davantage sur un NAS. Les textes très brefs, effets et panneaux hors cadre peuvent manquer. Aucun appel de traduction ne démarre ici.</p>
        <div className="modal-footer"><Button disabled={!validSample || create.isPending} onClick={() => create.mutate(paths)}>
          {create.isPending ? 'Ajout…' : `Lancer l’OCR sur ${paths.length} épisode${paths.length > 1 ? 's' : ''}`}
        </Button></div>
      </>}
      {id && query.isPending && <Spinner />}
      {query.isError && <ErrorNotice error={message(query.error)} retry={() => void query.refetch()} />}
      {task && <>
        <p><strong>{task.pause_requested ? 'Pause demandée' : labels[task.status]}</strong> · {task.index}/{task.total} images · {task.cue_count} répliques</p>
        <Progress value={task.progress} label="Progression OCR" />
        {task.error && <ErrorNotice error={task.error} />}
        <div className="ocr-actions">
          {['queued', 'running'].includes(task.status) && <Button variant="outline" disabled={action.isPending || task.pause_requested} onClick={() => action.mutate('pause')}>Mettre l’OCR en pause</Button>}
          {['paused', 'interrupted', 'error'].includes(task.status) && task.index < task.total && <Button disabled={action.isPending} onClick={() => action.mutate('resume')}>Reprendre l’OCR</Button>}
          {['queued', 'running', 'paused', 'interrupted'].includes(task.status) && <Button variant="outline" disabled={action.isPending} onClick={() => action.mutate('cancel')}>Annuler l’OCR</Button>}
          {!['queued', 'running'].includes(task.status) && <Button variant="ghost" disabled={action.isPending} onClick={() => setConfirmDelete(true)}>Retirer cette entrée OCR</Button>}
        </div>
        {confirmDelete && <div className="notice"><p>Retirer cette entrée et ses résultats OCR ? Les vidéos et les SRT déjà publiés restent sur disque. Les répliques non publiées seront perdues.</p>
          <div className="ocr-actions"><Button variant="outline" onClick={() => setConfirmDelete(false)}>Conserver l’extraction</Button>
            <Button disabled={action.isPending} onClick={() => action.mutate('delete')}>Retirer l’entrée OCR</Button></div>
        </div>}
        {task.status === 'review' && <>
          <label className="ocr-editor">SRT anglais — corrigez le texte et les timings si nécessaire
            <textarea aria-label="SRT anglais à vérifier" rows={12} maxLength={2_000_000} value={content} onChange={e => { setContent(e.target.value); setReviewed(false); }} />
          </label>
          <label className="ocr-check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />J’ai relu le SRT anglais. Je vérifierai aussi son affichage dans mon lecteur.</label>
          <p className="muted">Créer la source .en.ocr.srt à côté de la vidéo la rend sélectionnable dans l’explorateur. Les fichiers existants sont conservés. La traduction reste un lancement séparé.</p>
          <div className="modal-footer"><Button disabled={!reviewed || !content.trim() || publish.isPending} onClick={() => publish.mutate()}>
            {publish.isPending ? 'Création…' : 'Utiliser ce SRT anglais'}
          </Button></div>
        </>}
        {task.status === 'published' && <p className="notice">La source anglaise est disponible à côté de la vidéo. Scannez son dossier pour la sélectionner et la traduire.</p>}
      </>}
    </div>
  </Modal>;
}
