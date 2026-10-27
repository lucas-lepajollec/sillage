import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Episode, JobStatus, Track } from "./types";
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));
export const basename = (path: string) =>
  path.replace(/\/$/, "").split("/").pop() || path;
export const duration = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  if (m === 0) return `${Math.floor(seconds)} s`;
  return m >= 60
    ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`
    : `${m} min`;
};
export const timestamp = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.${String(Math.floor(ms % 1000)).padStart(3, "0")}`;
};
export const language = (code: string) =>
  ({
    eng: "Anglais",
    en: "Anglais",
    fra: "Français",
    fre: "Français",
    fr: "Français",
    jpn: "Japonais",
    ja: "Japonais",
    und: "Non précisée",
    "": "Non précisée",
  })[code.toLowerCase() as "en"] || code.toUpperCase();
export const trackLabel = (track: Track) =>
  `${language(track.language)} · ${track.format.toUpperCase()}${track.title ? ` · ${track.title}` : ""}${track.external ? " · externe" : ` · flux ${track.index ?? "?"}`}${track.default ? " · par défaut" : ""}${track.forced ? " · forcée" : ""}${track.sdh ? " · SDH" : ""}`;
export const preferredTrack = (episode: Episode) => {
  const english = episode.tracks.filter(
    (t) => t.supported && ["en", "eng"].includes(t.language.toLowerCase()),
  );
  const full = english.filter(
    (t) => !t.forced && !/signs?\s*(only|&|\/|and)/i.test(t.title),
  );
  return (
    full.find((t) => t.default) ||
    full.find((t) => !t.sdh) ||
    full[0] ||
    english[0] ||
    episode.tracks.find((t) => t.supported)
  );
};
export const canTranslate = (episode: Episode) =>
  !episode.error && episode.tracks.some((t) => t.supported);
export const jobLabels: Record<JobStatus, string> = {
  queued: "En attente",
  pausing: "Pause demandée",
  paused: "En pause",
  extracting: "Extraction",
  translating: "Traduction",
  validating: "Validation",
  syncing: "Synchronisation",
  writing: "Écriture",
  completed: "Terminé",
  error: "Erreur",
  review: "À vérifier",
  cancelled: "Annulé",
  interrupted: "Interrompu",
};
export const activeStatuses: JobStatus[] = [
  "queued",
  "pausing",
  "extracting",
  "translating",
  "validating",
  "syncing",
  "writing",
];
export const retryStatuses: JobStatus[] = ["paused", "error", "cancelled", "interrupted"];
export const timingLabel = (status: string) =>
  ({
    preserved: "Timings source préservés",
    source: "Timings source préservés",
    offset: "Décalage manuel appliqué",
    verified: "Synchronisation audio vérifiée",
    pending: "Proposition à vérifier",
    review: "Proposition à vérifier",
  })[status as "preserved"] ||
  status ||
  "Non vérifié";

// Keep large ASS effect counts readable; each affected event remains visible in the preview.
export function warningGroups(warnings: string[]) {
  const groups = new Map<string, number>();
  for (const warning of warnings) {
    const message = warning.replace(/^e[0-9]+\s*:\s*/, "");
    groups.set(message, (groups.get(message) || 0) + 1);
  }
  return [...groups].map(([message, count]) => ({ message, count }));
}
