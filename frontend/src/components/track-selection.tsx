import { useState } from "react";
import { Check, Subtitles } from "lucide-react";
import { preferredTrack, trackLabel } from "../lib";
import { matchSourceTrack, parentFolder } from "../tracks";
import type { Episode } from "../types";
import { Button } from "./ui/button";
import { Modal } from "./shared";

export function TrackSelection({ episodes, selected, tracks, initial, onClose, onApply }: {
  episodes: Episode[];
  selected: Episode[];
  tracks: Record<string, string>;
  initial?: Episode;
  onClose: () => void;
  onApply: (changes: Record<string, string | undefined>) => void;
}) {
  const available = episodes.filter((e) => !e.error && e.tracks.some((t) => t.supported));
  const first = initial || selected[0] || available[0];
  const [referencePath, setReferencePath] = useState(first?.path || "");
  const reference = available.find((e) => e.path === referencePath);
  const [trackId, setTrackId] = useState(first ? tracks[first.path] || preferredTrack(first)?.id || "" : "");
  const [scope, setScope] = useState(initial ? "folder" : selected.length ? "selected" : "all");
  const [folder, setFolder] = useState(first ? parentFolder(first.path) : "");
  const [mode, setMode] = useState("matching");
  const source = reference?.tracks.find((t) => t.id === trackId && t.supported);
  const targets = episodes.filter((e) => scope === "selected" ? selected.some((s) => s.path === e.path) : scope === "folder" ? parentFolder(e.path) === folder : true);
  const results = targets.map((episode) => ({ episode, ...(
    episode.error ? { reason: "Fichier non analysable : choix conservé." } :
    mode === "auto" ? { track: preferredTrack(episode), ...(!preferredTrack(episode) ? { reason: "Aucune piste textuelle prise en charge." } : {}) } :
    source ? matchSourceTrack(episode, source) : { reason: "Choisissez une piste de référence." }
  ) }));
  const matched = results.filter((r) => r.track);
  return (
    <Modal open onOpenChange={(open) => !open && onClose()} wide title="Choisir les pistes source"
      description="Préparez vos choix avant de traduire. Aucun appel à l’IA et aucun traitement en cours modifié.">
      <div className="track-selection-form">
        <label className="form-field">Appliquer à
          <select aria-label="Appliquer à" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="selected" disabled={!selected.length}>Épisodes sélectionnés ({selected.length})</option>
            <option value="folder">Un même dossier</option>
            <option value="all">Tous les épisodes du scan ({episodes.length})</option>
          </select>
        </label>
        {scope === "folder" && <label className="form-field">Dossier exact
          <select aria-label="Dossier exact" value={folder} onChange={(e) => setFolder(e.target.value)}>
            {[...new Set(episodes.map((e) => parentFolder(e.path)))].sort().map((path) => <option key={path}>{path}</option>)}
          </select>
          <small>Uniquement ce dossier parmi les résultats du scan, sans ses sous-dossiers.</small>
        </label>}
        <label className="form-field">Choix de piste
          <select aria-label="Choix de piste" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="matching">Utiliser une piste équivalente</option>
            <option value="auto">Revenir au choix automatique par épisode</option>
          </select>
        </label>
        {mode === "matching" && <>
          <label className="form-field">Épisode de référence
            <select aria-label="Épisode de référence" value={referencePath} onChange={(e) => {
              setReferencePath(e.target.value);
              const episode = available.find((item) => item.path === e.target.value)!;
              setTrackId(tracks[episode.path] || preferredTrack(episode)?.id || "");
            }}>
              {available.map((e) => <option key={e.path} value={e.path}>{e.name} · {parentFolder(e.path)}</option>)}
            </select>
          </label>
          <label className="form-field">Piste de référence
            <select aria-label="Piste de référence" value={trackId} onChange={(e) => setTrackId(e.target.value)}>
              {reference?.tracks.filter((t) => t.supported).map((t) => <option key={t.id} value={t.id}>{trackLabel(t)}</option>)}
            </select>
            <small>Même langue, titre, format et indicateurs forcée/SDH ; le numéro du flux peut varier. Pour les fichiers externes, le nom varie et n’est pas comparé. Toute correspondance ambiguë est ignorée.</small>
          </label>
        </>}
        <div className="track-apply-summary" role="status">
          <Subtitles size={17} />
          <span><strong>{matched.length} / {targets.length} épisode(s) avec une piste applicable</strong>
            <small>{targets.length - matched.length} sans changement · Les recherches et filtres ne limitent pas ce périmètre.</small>
          </span>
        </div>
        <ul className="track-match-list" aria-label="Vérification des correspondances">
          {results.map(({ episode, track, reason }) => <li key={episode.path}>
            <strong>{episode.name}</strong>
            <small>{parentFolder(episode.path)}</small>
            <span className={track ? "track-match-ok" : "track-match-skipped"}>{track ? trackLabel(track) : reason}</span>
          </li>)}
        </ul>
      </div>
      <div className="modal-footer">
        <Button variant="ghost" onClick={onClose}>Annuler</Button>
        <Button disabled={!matched.length} onClick={() => onApply(Object.fromEntries(matched.map(({ episode, track }) => [episode.path, mode === "auto" ? undefined : track!.id])))}>
          <Check size={15} />Appliquer à {matched.length} épisode(s)
        </Button>
      </div>
    </Modal>
  );
}
