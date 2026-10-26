import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Download,
  Eye,
  FolderOpen,
  Languages,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { api, downloadJob, message } from "../api";
import {
  activeStatuses,
  basename,
  cn,
  jobLabels,
  retryStatuses,
  timingLabel,
} from "../lib";
import type { Job, JobStatus } from "../types";
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
}: {
  jobs: Job[];
  loading: boolean;
  error: unknown;
  retry: () => void;
  notify: (text: string, error?: boolean) => void;
  onExplore: () => void;
}) {
  const client = useQueryClient();
  const [filter, setFilter] = useState<JobFilter>("all");
  const [search, setSearch] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [cancel, setCancel] = useState<Job | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const detail = jobs.find((j) => j.id === detailId);
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
    mutationFn: async () => {
      const failed = jobs.filter((j) => j.status === "error");
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
  const visible = jobs.filter(
    (job) =>
      `${job.name} ${job.path}`
        .toLocaleLowerCase("fr")
        .includes(search.toLocaleLowerCase("fr")) &&
      (filter === "all" ||
        (filter === "active" && activeStatuses.includes(job.status)) ||
        job.status === filter),
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
                onClick={() => setFilter("review")}
              >
                <AlertTriangle size={14} />
                {review.length} résultat{review.length > 1 ? "s" : ""} à
                vérifier
                <ArrowRight size={13} />
              </button>
            )}
          </div>
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
                  onClick={() => setFilter(item.value)}
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
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              {failed.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => bulkRetry.mutate()}
                  disabled={bulkRetry.isPending}
                >
                  <RotateCcw size={14} />
                  Reprendre les erreurs
                </Button>
              )}
            </div>
          </div>
          <div className="job-list">
            {visible.length === 0 && (
              <Empty icon={<Search size={26} />} title="Aucune traduction ici">
                Changez de filtre pour retrouver les autres épisodes.
              </Empty>
            )}
            {visible.map((job) => {
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
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </>
      )}
      <PreviewDrawer
        open={!!detail}
        job={detail}
        onClose={() => setDetailId(null)}
        notify={notify}
      />
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
