import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Folder,
  Eye,
  FolderOpen,
  Languages,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Search,
  ScanLine,
  ShieldCheck,
  X,
  Trash2,
  List,
} from "lucide-react";
import { api, downloadJob, message } from "../api";
import {
  activeStatuses,
  basename,
  cn,
  jobLabels,
  retryStatuses,
  timingLabel,
  trackLabel,
} from "../lib";
import type { Episode, Job, JobStatus, Reanalysis } from "../types";
import { groupJobFolders, jobFolderLabel } from "../job-folders";
import { parentFolder } from "../tracks";
import { Button } from "./ui/button";
import { Empty, ErrorNotice, Modal, Progress, Spinner, Status } from "./shared";
import { PreviewDrawer } from "./preview";

type JobFilter = "all" | "active" | "review" | "completed" | "error";
const stages: JobStatus[] = [
  "queued",
  "extracting",
  "translating",
  "validating",
  "syncing",
  "writing",
  "completed",
];
export function Translations({
  jobs,
  loading,
  error,
  retry,
  notify,
  onExplore,
  onReanalyzed,
}: {
  jobs: Job[];
  loading: boolean;
  error: unknown;
  retry: () => void;
  notify: (text: string, error?: boolean) => void;
  onExplore: () => void;
  onReanalyzed: (result: Reanalysis) => void;
}) {
  const client = useQueryClient();
  const [filter, setFilter] = useState<JobFilter>("all");
  const [search, setSearch] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(10);
  const [view, setView] = useState<"folders" | "list">(() => {
    try { return localStorage.getItem("sillage.jobs-view") === "list" ? "list" : "folders"; }
    catch { return "folders"; }
  });
  const [folder, setFolder] = useState<string | null>(null);
  const [remove, setRemove] = useState<Job[] | null>(null);
  useEffect(() => { localStorage.setItem("sillage.jobs-view", view); }, [view]);
  const paginationStart = useRef<HTMLElement>(null);
  const changeFilter = (next: JobFilter) => {
    setFilter(next);
    setPageIndex(0);
  };
  const [detailId, setDetailId] = useState<string | null>(null);
  const [cancel, setCancel] = useState<Job | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const detail = jobs.find((j) => j.id === detailId);
  const reanalyze = useMutation({
    mutationFn: (job: Job) => api<Episode>(`/jobs/${encodeURIComponent(job.id)}/reanalyze`, {}),
    onSuccess: (episode, job) => onReanalyzed({ episode, job }),
    onError: (e) => notify(message(e), true),
  });
  const deletion = useMutation({
    mutationFn: (entries: Job[]) => api<{ deleted: string[]; warnings: string[] }>("/jobs/delete", { ids: entries.map((j) => j.id) }),
    onSuccess: (result) => {
      client.setQueryData<Job[]>(["jobs"], (old) => old?.filter((job) => !result.deleted.includes(job.id)));
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setRemove(null);
      if (detailId && result.deleted.includes(detailId)) setDetailId(null);
      notify(result.warnings.length ? result.warnings.join(" ") : `${result.deleted.length} entrée${result.deleted.length > 1 ? "s" : ""} supprimée${result.deleted.length > 1 ? "s" : ""}. Les fichiers média et exports sont conservés.`, !!result.warnings.length);
    },
    onError: (e) => notify(message(e), true),
  });
  const requestDeletion = (entries: Job[]) => { deletion.reset(); setRemove(entries); };
  const mutation = useMutation({
    mutationFn: ({ job, action }: { job: Job; action: "resume" | "cancel" }) =>
      api<Job>(`/jobs/${encodeURIComponent(job.id)}/${action}`, {}),
    onSuccess: (_, variables) => {
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setCancel(null);
      notify(
        variables.action === "resume"
          ? "Reprise demandée depuis le dernier checkpoint."
          : "Annulation demandée. Les segments validés sont conservés.",
      );
    },
    onError: (e) => notify(message(e), true),
  });
  const bulkRetry = useMutation({
    mutationFn: async (failed: Job[]) => {
      const results = await Promise.allSettled(
        failed.map((job) =>
          api<Job>(`/jobs/${encodeURIComponent(job.id)}/resume`, {}),
        ),
      );
      const errors = results.filter((r) => r.status === "rejected");
      if (errors.length)
        throw new Error(
          `${failed.length - errors.length} reprise(s) demandée(s), ${errors.length} échec(s).`,
        );
    },
    onSettled: () => void client.invalidateQueries({ queryKey: ["jobs"] }),
    onSuccess: () =>
      notify("Les épisodes en erreur ont été remis dans la file."),
    onError: (e) => notify(message(e), true),
  });
  const active = jobs.filter((j) => activeStatuses.includes(j.status));
  const complete = jobs.filter((j) => j.status === "completed");
  const review = jobs.filter((j) => j.status === "review");
  const failed = jobs.filter((j) => j.status === "error");
  const processable = jobs.filter(
    (j) =>
      activeStatuses.includes(j.status) ||
      ["completed", "review"].includes(j.status),
  );
  const overall = processable.length
    ? processable.reduce((n, j) => n + j.progress, 0) / processable.length
    : 0;
  const matching = jobs.filter(
    (job) =>
      `${job.name} ${job.path}`
        .toLocaleLowerCase("fr")
        .includes(search.toLocaleLowerCase("fr")) &&
      (filter === "all" ||
        (filter === "active" && activeStatuses.includes(job.status)) ||
        job.status === filter),
  );
  const visible = view === "folders" && folder !== null ? matching.filter((job) => parentFolder(job.path) === folder) : matching;
  const folders = groupJobFolders(matching);
  const showFolders = view === "folders" && folder === null;
  const totalItems = showFolders ? folders.length : visible.length;
  const inactive = visible.filter((job) => !activeStatuses.includes(job.status)).slice(0, 500);
  const scopedFailed = visible.filter((job) => job.status === "error");
  const pageCount = Math.max(1, Math.ceil(totalItems / pageSize));
  const currentPage = Math.min(pageIndex, pageCount - 1);
  const pageJobs = showFolders ? [] : visible.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const pageFolders = showFolders ? folders.slice(currentPage * pageSize, (currentPage + 1) * pageSize) : [];
  useEffect(() => {
    setPageIndex((index) => Math.min(index, pageCount - 1));
  }, [pageCount]);
  const goToPage = (index: number) => {
    setPageIndex(index);
    paginationStart.current?.scrollIntoView({ block: "start" });
    paginationStart.current?.focus({ preventScroll: true });
  };
  const pagination = (position: "top" | "bottom") => (
    <nav
      className="jobs-pagination"
      aria-label={`Pagination des traductions ${position === "top" ? "en haut" : "en bas"}`}
      ref={position === "top" ? paginationStart : undefined}
      tabIndex={-1}
    >
      <span className="jobs-page-range" aria-live={position === "top" ? "polite" : undefined} aria-atomic="true">
        {currentPage * pageSize + 1}–{Math.min((currentPage + 1) * pageSize, totalItems)} sur {totalItems} {showFolders ? "dossiers" : "traductions"}
      </span>
      <div className="jobs-page-controls">
        {position === "top" && (
          <label className="jobs-page-size">
            Par page
            <select
              aria-label={showFolders ? "Dossiers par page" : "Traductions par page"}
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPageIndex(0);
              }}
            >
              {[5, 10, 25].map((size) => <option key={size}>{size}</option>)}
            </select>
          </label>
        )}
        <span className="jobs-page-number">Page {currentPage + 1} / {pageCount}</span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Page précédente"
          disabled={currentPage === 0}
          onClick={() => goToPage(currentPage - 1)}
        >
          <ChevronLeft size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Page suivante"
          disabled={currentPage === pageCount - 1}
          onClick={() => goToPage(currentPage + 1)}
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    </nav>
  );
  const download = async (job: Job) => {
    setDownloading(job.id);
    try {
      await downloadJob(job.id, basename(job.output || `${job.name}.fr.srt`));
      notify("Sous-titre téléchargé.");
    } catch (e) {
      notify(message(e), true);
    } finally {
      setDownloading(null);
    }
  };
  return (
    <div className="page translations-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">DE L’ORIGINAL AU FRANÇAIS</div>
          <h1>Traductions</h1>
          <p>Chaque épisode, chaque étape. Gardez le fil.</p>
        </div>
        <Button variant="outline" onClick={onExplore}>
          <FolderOpen size={15} />
          Choisir des épisodes
          <ArrowRight size={14} />
        </Button>
      </div>
      {loading && <Spinner>Chargement de la file de traduction…</Spinner>}
      {!!error && <ErrorNotice error={message(error)} retry={retry} />}
      {!loading && !error && jobs.length === 0 && (
        <section className="jobs-empty-surface">
          <Empty
            icon={<Languages size={32} />}
            title="De nouvelles voix vous attendent."
            action={
              <Button onClick={onExplore}>
                <FolderOpen size={16} />
                Explorer ma médiathèque
                <ArrowRight size={15} />
              </Button>
            }
          >
            Scannez un dossier, sélectionnez vos épisodes et lancez une
            traduction. Leur progression apparaîtra ici.
          </Empty>
          <div className="empty-job-steps">
            {["Extraction", "Traduction", "Validation", "Export"].map(
              (label, i) => (
                <span key={label}>
                  <b>{String(i + 1).padStart(2, "0")}</b>
                  {label}
                  {i < 3 && <ArrowRight size={13} />}
                </span>
              ),
            )}
          </div>
        </section>
      )}
      {jobs.length > 0 && (
        <>
          <div className="queue-summary">
            <div className="queue-summary-top">
              <div>
                <span
                  className={cn(
                    "queue-indicator",
                    active.length > 0 && "running",
                  )}
                >
                  {active.length ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Check size={16} />
                  )}
                </span>
                <strong>
                  {active.length
                    ? `${active.length} opération${active.length > 1 ? "s" : ""} en cours`
                    : review.length
                      ? "Des résultats sont à vérifier"
                      : "La file est au repos"}
                </strong>
                <span className="muted">
                  {complete.length} / {jobs.length} terminé
                  {complete.length > 1 ? "s" : ""}
                </span>
              </div>
              <span className="queue-percentage">{Math.round(overall)} %</span>
            </div>
            <Progress
              value={overall}
              label="Progression globale des traductions"
            />
            {review.length > 0 && (
              <button
                className="review-link"
                onClick={() => { changeFilter("review"); setFolder(null); }}
              >
                <AlertTriangle size={14} />
                {review.length} résultat{review.length > 1 ? "s" : ""} à
                vérifier
                <ArrowRight size={13} />
              </button>
            )}
          </div>
          <div className="jobs-view-toolbar">
            <div className="jobs-view-toggle" role="group" aria-label="Vue des traductions">
              <Button variant={view === "folders" ? "default" : "outline"} size="sm" aria-pressed={view === "folders"}
                onClick={() => { setView("folders"); setFolder(null); setPageIndex(0); }}><Folder size={15} />Dossiers</Button>
              <Button variant={view === "list" ? "default" : "outline"} size="sm" aria-pressed={view === "list"}
                onClick={() => { setView("list"); setFolder(null); setPageIndex(0); }}><List size={15} />Liste</Button>
            </div>
            {!showFolders && inactive.length > 0 && <Button variant="outline" size="sm" disabled={deletion.isPending}
              onClick={() => requestDeletion(inactive)}><Trash2 size={14} />Nettoyer l’historique ({inactive.length})</Button>}
          </div>
          {view === "folders" && <nav className="jobs-folder-navigation" aria-label="Dossiers des traductions">
            <Button variant="ghost" size="sm" onClick={() => { setFolder(null); setPageIndex(0); }}><FolderOpen size={14} />Tous les dossiers</Button>
            {folder !== null && <><ChevronRight size={13} /><strong>{jobFolderLabel(folder)}</strong><small>{folder}</small></>}
          </nav>}
          <div className="jobs-toolbar">
            <div className="job-filters" aria-label="Filtrer les traductions">
              {(
                [
                  { value: "all", label: "Tout", count: jobs.length },
                  { value: "active", label: "En cours", count: active.length },
                  {
                    value: "review",
                    label: "À vérifier",
                    count: review.length,
                  },
                  {
                    value: "completed",
                    label: "Terminées",
                    count: complete.length,
                  },
                  { value: "error", label: "Erreurs", count: failed.length },
                ] as const
              ).map((item) => (
                <button
                  key={item.value}
                  className={filter === item.value ? "active" : ""}
                  onClick={() => changeFilter(item.value)}
                  aria-pressed={filter === item.value}
                >
                  {item.label}
                  <span>{item.count}</span>
                </button>
              ))}
            </div>
            <div className="jobs-toolbar-actions">
              <div className="input-icon">
                <Search size={14} />
                <input
                  aria-label="Rechercher une traduction"
                  placeholder="Rechercher…"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPageIndex(0);
                  }}
                />
              </div>
              {!showFolders && scopedFailed.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => bulkRetry.mutate(scopedFailed)}
                  disabled={bulkRetry.isPending}
                >
                  <RotateCcw size={14} />
                  Reprendre les erreurs ({scopedFailed.length})
                </Button>
              )}
            </div>
          </div>
          {totalItems > 0 && pagination("top")}
          {showFolders && <div className="job-folder-grid">
            {pageFolders.map((entry) => <button className="job-folder-card" key={entry.path}
              aria-label={`Ouvrir le dossier ${entry.path}`} onClick={() => { setFolder(entry.path); setPageIndex(0); }}>
              <Folder size={24} /><span><strong>{jobFolderLabel(entry.path)}</strong><small>{entry.path}</small>
                <span>{entry.count} traduction{entry.count > 1 ? "s" : ""} · {entry.active} en cours · {entry.errors} en erreur{entry.review > 0 ? ` · ${entry.review} à vérifier` : ""}</span>
              </span><ChevronRight size={16} />
            </button>)}
          </div>}
          <div className="job-list">
            {totalItems === 0 && (
              <Empty icon={<Search size={26} />} title="Aucune traduction ici">
                Changez de filtre pour retrouver les autres épisodes.
              </Empty>
            )}
            {pageJobs.map((job) => {
              const isActive = activeStatuses.includes(job.status);
              const jobStages = stages.filter(
                (stage) => stage !== "syncing" || job.sync_mode !== "preserve",
              );
              const currentStage = jobStages.indexOf(job.status);
              return (
                <article
                  className={cn("job-card", `job-${job.status}`)}
                  key={job.id}
                >
                  <div className="job-card-heading">
                    <span
                      className={cn(
                        "job-symbol",
                        job.status === "completed" && "complete",
                      )}
                    >
                      {job.status === "completed" ? (
                        <Check size={20} />
                      ) : job.status === "error" || job.status === "review" ? (
                        <AlertTriangle size={20} />
                      ) : isActive ? (
                        <Languages size={20} />
                      ) : (
                        <Pause size={20} />
                      )}
                    </span>
                    <button
                      className="job-title"
                      onClick={() => setDetailId(job.id)}
                    >
                      <strong>{job.name}</strong>
                      <small>
                        {job.path.slice(0, -job.name.length).replace(/\/$/, "")}
                      </small>
                    </button>
                    <Status status={job.status} />
                    <span className="job-percent">
                      {Math.round(job.progress)}
                      <small>%</small>
                    </span>
                  </div>
                  <Progress
                    value={job.progress}
                    label={`Progression de ${job.name}`}
                  />
                  <div className="job-source-track">
                    <Languages size={13} />
                    <span>Piste source : {job.source_track ? trackLabel(job.source_track) : `${job.track_id} · libellé non enregistré`}</span>
                  </div>
                  <div className="job-stages">
                    {jobStages.map((stage, i) => (
                      <span
                        key={stage}
                        className={cn(
                          "job-stage",
                          (currentStage > i || job.status === "completed") &&
                            "done",
                          job.status === stage && "current",
                        )}
                      >
                        <span>
                          {currentStage > i || job.status === "completed" ? (
                            <Check size={10} />
                          ) : (
                            i + 1
                          )}
                        </span>
                        {jobLabels[stage]}
                      </span>
                    ))}
                  </div>
                  {job.error && (
                    <div className="job-error">
                      <AlertTriangle size={14} />
                      <span>{job.error}</span>
                    </div>
                  )}
                  {job.warnings.length > 0 && (
                    <details className="job-warnings">
                      <summary>
                        <AlertTriangle size={13} />
                        {job.warnings.length} avertissement
                        {job.warnings.length > 1 ? "s" : ""}
                      </summary>
                      {job.warnings.map((warning, i) => (
                        <p key={i}>{warning}</p>
                      ))}
                    </details>
                  )}
                  <div className="job-card-footer">
                    <span>
                      {job.total
                        ? `${job.done} / ${job.total} segments`
                        : "Segments en préparation"}
                      {job.adaptive_batch_size && (
                        <> · Lots ≤ {job.adaptive_batch_size} répliques</>
                      )}
                      <span className="footer-dot">·</span>
                      {job.sync_mode === "preserve" ? (
                        <>
                          <ShieldCheck size={12} />
                          Timings source
                        </>
                      ) : (
                        timingLabel(job.timing_status)
                      )}
                    </span>
                    <div>
                      <Button variant="ghost" size="sm" aria-label={`Réanalyser ${job.name}`}
                        disabled={reanalyze.isPending} onClick={() => reanalyze.mutate(job)}>
                        {reanalyze.isPending && reanalyze.variables?.id === job.id ? <Loader2 className="spin" size={14} /> : <ScanLine size={14} />}Réanalyser
                      </Button>
                      {job.status !== "queued" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDetailId(job.id)}
                        >
                          <Eye size={14} />
                          {job.sync_pending
                            ? "Vérifier la proposition"
                            : "Aperçu"}
                        </Button>
                      )}
                      {isActive && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setCancel(job)}
                          disabled={mutation.isPending}
                        >
                          <X size={14} />
                          Annuler
                        </Button>
                      )}
                      {retryStatuses.includes(job.status) && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            mutation.mutate({ job, action: "resume" })
                          }
                          disabled={mutation.isPending}
                        >
                          <Play size={13} />
                          Reprendre
                        </Button>
                      )}
                      {job.output && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void download(job)}
                          disabled={downloading === job.id}
                        >
                          {downloading === job.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Download size={14} />
                          )}
                          Télécharger
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" aria-label={`Supprimer de l’historique ${job.name}`}
                        disabled={isActive || deletion.isPending} title={isActive ? "Annulez le traitement avant de le supprimer." : "Supprimer l’entrée et ses checkpoints, conserver les fichiers média et exports."}
                        onClick={() => requestDeletion([job])}><Trash2 size={14} />Supprimer</Button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
          {pageCount > 1 && pagination("bottom")}
        </>
      )}
      <PreviewDrawer
        open={!!detail}
        job={detail}
        onClose={() => setDetailId(null)}
        notify={notify}
      />
      <Modal open={!!remove} onOpenChange={(open) => { if (!open && !deletion.isPending) setRemove(null); }}
        title="Supprimer de l’historique ?" description={`${remove?.length || 0} entrée${(remove?.length || 0) > 1 ? "s" : ""} sélectionnée${(remove?.length || 0) > 1 ? "s" : ""}`}>
        <p className="modal-body-copy">Les entrées, leurs checkpoints et fichiers de travail seront supprimés. Les MKV, pistes source et sous-titres déjà exportés restent sur votre disque. Les traitements actifs sont exclus.</p>
        <ul className="history-delete-list">{remove?.slice(0, 5).map((job) => <li key={job.id}>{job.name}<small>{parentFolder(job.path)}</small></li>)}</ul>
        {remove && remove.length > 5 && <p className="modal-body-copy">Et {remove.length - 5} autre{remove.length > 6 ? "s" : ""} entrée{remove.length > 6 ? "s" : ""}. Le nettoyage suit le dossier, la recherche et les filtres affichés, sur toutes les pages (500 entrées maximum à la fois).</p>}
        {deletion.isError && <ErrorNotice error={message(deletion.error)} />}
        <div className="modal-footer">
          <Button variant="outline" disabled={deletion.isPending} onClick={() => setRemove(null)}>Conserver</Button>
          <Button variant="destructive" disabled={deletion.isPending || !remove?.length} onClick={() => remove && deletion.mutate(remove)}>
            <Trash2 size={14} />{deletion.isPending ? "Suppression…" : "Supprimer définitivement ces entrées"}
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!cancel}
        onOpenChange={(open) => {
          if (!open) setCancel(null);
        }}
        title="Annuler cette traduction ?"
        description={cancel?.name}
      >
        <p className="modal-body-copy">
          Les segments déjà validés restent enregistrés. Vous pourrez reprendre
          le traitement plus tard depuis le dernier checkpoint.
        </p>
        <div className="modal-footer">
          <Button variant="outline" onClick={() => setCancel(null)}>
            Continuer la traduction
          </Button>
          <Button
            variant="destructive"
            onClick={() =>
              cancel && mutation.mutate({ job: cancel, action: "cancel" })
            }
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Annulation…" : "Annuler le traitement"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
