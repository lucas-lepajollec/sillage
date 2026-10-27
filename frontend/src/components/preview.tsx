import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Clock3,
  FileVideo2,
  Languages,
  Search,
  ShieldCheck,
  Sparkles,
  Subtitles,
  X,
} from "lucide-react";
import { api, message } from "../api";
import {
  activeStatuses,
  cn,
  duration,
  timestamp,
  timingLabel,
  trackLabel,
  warningGroups,
} from "../lib";
import type { Episode, Job, Preview } from "../types";
import { Button } from "./ui/button";
import { Empty, ErrorNotice, Spinner, Status } from "./shared";

export function PreviewDrawer({
  open,
  onClose,
  episode,
  job,
  trackId,
  onTrackChange,
  trackSelectionMode,
  onTrackReset,
  onApplyToGroup,
  notify,
}: {
  open: boolean;
  onClose: () => void;
  episode?: Episode | null;
  job?: Job | null;
  trackId?: string;
  onTrackChange?: (id: string) => void;
  trackSelectionMode?: "auto" | "manual";
  onTrackReset?: () => void;
  onApplyToGroup?: () => void;
  notify: (text: string, error?: boolean) => void;
}) {
  const client = useQueryClient();
  const [tab, setTab] = useState<"cues" | "details">("cues");
  const [search, setSearch] = useState("");
  const [onlyWarnings, setOnlyWarnings] = useState(false);
  const [showTags, setShowTags] = useState(false);
  const sourceTrack = episode?.tracks.find((t) => t.id === trackId);
  const query = useQuery({
    queryKey: ["preview", job?.id || episode?.path, job ? "job" : trackId],
    queryFn: () =>
      job
        ? api<Preview>(`/jobs/${encodeURIComponent(job.id)}/preview`)
        : api<Preview>("/preview", { path: episode!.path, track_id: trackId }),
    enabled: open && (!!job || !!(episode && sourceTrack?.supported)),
    staleTime: 0,
    refetchInterval: job && activeStatuses.includes(job.status) ? 3000 : false,
  });
  const decision = useMutation({
    mutationFn: (accept: boolean) =>
      api<Job>(
        `/jobs/${encodeURIComponent(job!.id)}/sync/${accept ? "accept" : "reject"}`,
        {},
      ),
    onSuccess: (_, accept) => {
      void client.invalidateQueries({ queryKey: ["jobs"] });
      void query.refetch();
      notify(
        accept
          ? "Correction acceptée. Le sous-titre est exporté."
          : "Timings source conservés. Le sous-titre est exporté.",
      );
      onClose();
    },
    onError: (error) => notify(message(error), true),
  });
  useEffect(() => {
    setTab("cues");
    setSearch("");
    setOnlyWarnings(false);
    setShowTags(false);
  }, [episode?.path, job?.id, trackId]);
  const data = query.data;
  const displayedTrack = job ? data?.source_track || job.source_track : sourceTrack;
  const cues =
    data?.cues.filter(
      (cue) =>
        (!search ||
          `${cue.text} ${cue.translated || ""}`
            .toLocaleLowerCase("fr")
            .includes(search.toLocaleLowerCase("fr"))) &&
        (!onlyWarnings || cue.warning),
    ) || [];
  const hasTranslations = !!data?.cues.some(
    (cue) => cue.translated !== undefined,
  );
  const proposed = data?.sync_proposal ?? job?.sync_proposal;
  const reviewing = !!job?.sync_pending;
  const readable = (text: string) =>
    showTags
      ? text
      : text
          .replace(/\{[^}]*\}/g, "")
          .replace(/<[^>]*>/g, "")
          .replace(/\\[Nn]/g, "\n")
          .replace(/\\h/g, " ");
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content
          className="preview-drawer"
          aria-describedby="preview-description"
        >
          <div className="drawer-top">
            <span className="eyebrow">
              <Subtitles size={14} />
              APERÇU DES SOUS-TITRES
            </span>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Fermer l’aperçu">
                <X size={19} />
              </Button>
            </Dialog.Close>
          </div>
          <div className="drawer-heading">
            <span className="file-icon">
              <FileVideo2 size={23} />
            </span>
            <div>
              <Dialog.Title>{episode?.name || job?.name}</Dialog.Title>
              <Dialog.Description id="preview-description">
                {episode?.path || job?.path}
              </Dialog.Description>
            </div>
          </div>
          <div className="drawer-meta">
            {job && <Status status={job.status} />}
            {episode && (
              <span>
                <Clock3 size={13} />
                {duration(episode.duration)}
              </span>
            )}
            {data && (
              <span className="format-label">{data.format.toUpperCase()}</span>
            )}
            <span>
              <Subtitles size={13} />
              {data ? `${data.cues.length} événements` : "Piste source"}
            </span>
          </div>
          <div
            className="drawer-tabs"
            role="tablist"
            aria-label="Détails du sous-titre"
          >
            <button
              id="cues-tab"
              role="tab"
              aria-selected={tab === "cues"}
              aria-controls="cues-panel"
              className={tab === "cues" ? "active" : ""}
              onClick={() => setTab("cues")}
            >
              Répliques{hasTranslations && <span>EN / FR</span>}
            </button>
            <button
              id="details-tab"
              role="tab"
              aria-selected={tab === "details"}
              aria-controls="details-panel"
              className={tab === "details" ? "active" : ""}
              onClick={() => setTab("details")}
            >
              {episode ? "Pistes et fichier" : "Traitement"}
            </button>
          </div>
          <div className="drawer-content">
            <section className="source-track-info" aria-label="Informations de la piste source">
              <span className="eyebrow">{job ? "PISTE DU TRAITEMENT" : "PISTE À TRADUIRE"}</span>
              <strong>{displayedTrack ? trackLabel(displayedTrack) : job ? `Identifiant : ${job.track_id}` : "Choisissez une piste"}</strong>
              {displayedTrack && (displayedTrack.forced || /signs?\s*(only|&|\/|and)|panneaux/i.test(displayedTrack.title)) &&
                <small className="source-track-caution">Piste forcée ou de panneaux/chansons : elle peut ne pas contenir les dialogues complets.</small>}
              {job ? <small>
                {data?.source_track_origin === "current" ? "Ancien traitement : libellé lu dans le fichier actuel, non enregistré au lancement. " :
                  !displayedTrack ? "Le libellé de cette ancienne piste n’a pas été enregistré. " : "Piste enregistrée pour ce traitement. "}
                Reprendre utilise cette même piste. Pour en changer, créez une nouvelle traduction dans l’explorateur.
              </small> : <>
                <small>{trackSelectionMode === "manual" ? "Votre choix pour cet épisode." : "Choix automatique : priorité à une piste anglaise complète par défaut."} Les choix préparés seront utilisés au lancement de la traduction ; un nouveau scan les réinitialise.</small>
                <label className="preview-track-label">Piste à prévisualiser
                  <select aria-label="Piste à prévisualiser" value={trackId || ""} onChange={(e) => onTrackChange?.(e.target.value)}>
                    {episode?.tracks.map((track) => <option key={track.id} value={track.id} disabled={!track.supported}>
                      {trackLabel(track)}{!track.supported ? " · graphique, non traduit" : ""}
                    </option>)}
                  </select>
                </label>
                <div className="source-track-actions">
                  {trackSelectionMode === "manual" && <Button variant="ghost" size="sm" onClick={onTrackReset}>Revenir au choix automatique</Button>}
                  <Button variant="outline" size="sm" onClick={onApplyToGroup}>Appliquer à d’autres épisodes</Button>
                </div>
              </>}
              {data?.stats && <div className="source-track-stats" aria-label="Comptage des événements">
                <span><b>{data.stats.translatable}</b> à traduire par l’IA</span>
                <span><b>{data.stats.preserved}</b> conservés sans traduction</span>
                {!!data.stats.frame_animation && <span><b>{data.stats.frame_animation}</b> effets image par image conservés à l’identique</span>}
              </div>}
              {!job && <small>L’aperçu n’appelle pas l’IA. Un événement ASS n’est pas forcément une phrase unique.</small>}
            </section>
            {data && (
              <div
                className={cn("timing-notice", reviewing && "review-notice")}
              >
                {reviewing ? <Sparkles size={16} /> : <ShieldCheck size={16} />}
                <div>
                  <strong>{timingLabel(data.timing_status)}</strong>
                  <small>
                    {reviewing
                      ? "Aucun fichier final n’est publié avant votre décision."
                      : job?.sync_mode === "preserve" || !job
                        ? "Préserver les timings ne vérifie pas la synchronisation audio."
                        : "Consultez les avertissements et les répliques ci-dessous."}
                  </small>
                </div>
              </div>
            )}
            {reviewing && proposed && (
              <div className="sync-proposal">
                <div>
                  <span>Décalage proposé</span>
                  <strong>
                    {proposed.offset_ms > 0 ? "+" : ""}
                    {proposed.offset_ms} <small>ms</small>
                  </strong>
                </div>
                {Number.isFinite(proposed.confidence) && (
                  <div>
                    <span>Corrélation audio / texte</span>
                    <strong>{proposed.confidence.toFixed(2)}</strong>
                  </div>
                )}
                <p>
                  Les timestamps proposés sont affichés sous les timestamps
                  source. Accepter applique cette correction à l’export.
                </p>
                {proposed.warnings.map((warning, i) => (
                  <p className="warning-line" key={i}>
                    <AlertTriangle size={13} />
                    {warning}
                  </p>
                ))}
              </div>
            )}
            {data && data.warnings.length > 0 && (
              <details
                className="preview-warnings"
                open={reviewing || undefined}
              >
                <summary>
                  <AlertTriangle size={14} />
                  {data.warnings.length} avertissement
                  {data.warnings.length > 1 ? "s" : ""}
                </summary>
                {warningGroups(data.warnings).map(({ message, count }) => (
                  <p key={message}>{count > 1 ? `${count} événements · ` : ""}{message}</p>
                ))}
              </details>
            )}
            {tab === "cues" && (
              <div role="tabpanel" id="cues-panel" aria-labelledby="cues-tab">
                {query.isPending && (job || sourceTrack?.supported) && (
                  <Spinner>Lecture des répliques…</Spinner>
                )}
                {query.isError && (
                  <ErrorNotice
                    error={message(query.error)}
                    retry={() => void query.refetch()}
                  />
                )}
                {episode && (!sourceTrack || !sourceTrack.supported) && (
                  <Empty
                    icon={<Subtitles size={27} />}
                    title={
                      sourceTrack
                        ? "Une piste graphique"
                        : "Choisissez une piste textuelle"
                    }
                  >
                    {sourceTrack
                      ? "Les sous-titres PGS et VobSub sont détectés, mais leur traduction nécessite de l’OCR, hors périmètre de cet atelier."
                      : "Aucune piste textuelle exploitable n’est sélectionnée pour ce fichier."}
                  </Empty>
                )}
                {data && (
                  <>
                    <div className="preview-search">
                      <div className="input-icon">
                        <Search size={14} />
                        <input
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                          placeholder="Rechercher une réplique…"
                          aria-label="Rechercher dans les répliques"
                        />
                      </div>
                      <label>
                        <input
                          type="checkbox"
                          checked={showTags}
                          onChange={(e) => setShowTags(e.target.checked)}
                        />
                        Balises
                      </label>
                      {data.cues.some((cue) => cue.warning) && (
                        <label>
                          <input
                            type="checkbox"
                            checked={onlyWarnings}
                            onChange={(e) => setOnlyWarnings(e.target.checked)}
                          />
                          À vérifier
                        </label>
                      )}
                    </div>
                    <div className="cue-column-labels">
                      <span>TIMINGS</span>
                      <span>
                        {hasTranslations
                          ? "SOURCE / TRADUCTION"
                          : "TEXTE SOURCE"}
                      </span>
                    </div>
                    {cues.length === 0 && (
                      <Empty
                        icon={<Languages size={26} />}
                        title={
                          data.cues.length
                            ? "Aucune réplique correspondante"
                            : "Aucune réplique disponible"
                        }
                      >
                        {job && activeStatuses.includes(job.status)
                          ? "L’aperçu se remplira au fil du traitement."
                          : "Le sous-titre ne contient aucune réplique pour cet aperçu."}
                      </Empty>
                    )}
                    <ol className="cue-list">
                      {cues.map((cue) => (
                        <li
                          className={cn("cue", cue.warning && "cue-warning")}
                          key={cue.id}
                        >
                          <div className="cue-timing">
                            <span className="cue-id">#{cue.id}</span>
                            <time>{timestamp(cue.start)}</time>
                            <time>{timestamp(cue.end)}</time>
                            {cue.proposed_start !== undefined && (
                              <div className="proposed-timing">
                                <ArrowRight size={11} />
                                <time>{timestamp(cue.proposed_start)}</time>
                                <time>
                                  {timestamp(cue.proposed_end ?? cue.end)}
                                </time>
                              </div>
                            )}
                          </div>
                          <div className="cue-text">
                            <p
                              className={
                                hasTranslations
                                  ? "cue-source translated-source"
                                  : "cue-source"
                              }
                            >
                              {readable(cue.text)}
                            </p>
                            {cue.translated !== undefined && (
                              <p className="cue-translated">
                                {readable(cue.translated)}
                              </p>
                            )}
                            {cue.warning && (
                              <p className="cue-warning-text">
                                <AlertTriangle size={12} />
                                {cue.warning}
                              </p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </div>
            )}
            {tab === "details" && (
              <div
                role="tabpanel"
                id="details-panel"
                aria-labelledby="details-tab"
              >
                {episode && (
                  <>
                    <div className="detail-section">
                      <h3>Fichier source</h3>
                      <dl>
                        <div>
                          <dt>Durée</dt>
                          <dd>{duration(episode.duration)}</dd>
                        </div>
                        <div>
                          <dt>Français</dt>
                          <dd>
                            {episode.has_french
                              ? "Déjà présent"
                              : "Non détecté"}
                          </dd>
                        </div>
                        <div>
                          <dt>Emplacement</dt>
                          <dd className="break-path">{episode.path}</dd>
                        </div>
                      </dl>
                      {episode.error && <ErrorNotice error={episode.error} />}
                    </div>
                    <div className="detail-section">
                      <h3>
                        {episode.tracks.length} piste
                        {episode.tracks.length > 1 ? "s" : ""} de sous-titres
                      </h3>
                      <div className="track-list">
                        {episode.tracks.map((track) => (
                          <div className="track-detail" key={track.id}>
                            <Subtitles size={17} />
                            <div>
                              <strong>{trackLabel(track)}</strong>
                              <div className="track-badges">
                                {track.default && <span>Par défaut</span>}
                                {track.forced && <span>Forcée</span>}
                                {track.sdh && <span>SDH</span>}
                                {track.external && <span>Fichier externe</span>}
                                {!track.supported && (
                                  <span className="unsupported-badge">
                                    Format non traduisible
                                  </span>
                                )}
                              </div>
                              {track.path && (
                                <small className="break-path">
                                  {track.path}
                                </small>
                              )}
                            </div>
                            {track.supported && onTrackChange && (
                              <Button
                                size="sm"
                                variant={
                                  track.id === trackId ? "default" : "outline"
                                }
                                onClick={() => {
                                  onTrackChange(track.id);
                                  setTab("cues");
                                }}
                              >
                                {track.id === trackId ? (
                                  <Check size={13} />
                                ) : (
                                  "Choisir"
                                )}
                              </Button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                )}
                {job && (
                  <div className="detail-section">
                    <h3>Traitement</h3>
                    <dl>
                      <div>
                        <dt>Statut</dt>
                        <dd>
                          <Status status={job.status} />
                        </dd>
                      </div>
                      <div>
                        <dt>Progression</dt>
                        <dd>
                          {job.done} / {job.total} segments ·{" "}
                          {Math.round(job.progress)} %
                        </dd>
                      </div>
                      <div>
                        <dt>Synchronisation</dt>
                        <dd>
                          {job.sync_mode === "preserve"
                            ? "Timings source"
                            : job.sync_mode === "offset"
                              ? `${job.offset_ms} ms manuels`
                              : "Correction automatique"}
                        </dd>
                      </div>
                      <div>
                        <dt>Créé le</dt>
                        <dd>
                          {new Date(job.created_at).toLocaleString("fr-FR")}
                        </dd>
                      </div>
                      {job.output && (
                        <div>
                          <dt>Sous-titre produit</dt>
                          <dd className="break-path">{job.output}</dd>
                        </div>
                      )}
                    </dl>
                    {job.error && <ErrorNotice error={job.error} />}
                  </div>
                )}
              </div>
            )}
          </div>
          {reviewing ? (
            <div className="drawer-review-footer">
              <p>
                {proposed
                  ? "Après comparaison, choisissez les timings de l’export."
                  : "Aucune correction fiable proposée. Conservez les timings source."}
              </p>
              <div>
                <Button
                  variant="outline"
                  onClick={() => decision.mutate(false)}
                  disabled={decision.isPending}
                >
                  Conserver les timings source
                </Button>
                {proposed && (
                  <Button
                    onClick={() => decision.mutate(true)}
                    disabled={decision.isPending}
                  >
                    <Check size={15} />
                    Accepter la correction
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="drawer-footer">
              <ShieldCheck size={13} />
              L’aperçu ne modifie aucun fichier.
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
