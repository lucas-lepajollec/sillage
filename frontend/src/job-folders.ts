import { activeStatuses } from "./lib";
import { parentFolder } from "./tracks";
import type { Job } from "./types";

export const jobFolderLabel = (path: string) => path.split("/").filter(Boolean).slice(-2).join(" / ") || "Racine";

export function groupJobFolders(jobs: Job[]) {
  const groups = new Map<string, Job[]>();
  for (const job of jobs) {
    const path = parentFolder(job.path);
    const entries = groups.get(path) || [];
    entries.push(job);
    groups.set(path, entries);
  }
  return [...groups].map(([path, entries]) => ({
    path, count: entries.length,
    active: entries.filter((job) => activeStatuses.includes(job.status)).length,
    errors: entries.filter((job) => job.status === "error").length,
    review: entries.filter((job) => job.status === "review").length,
  })).sort((a, b) => a.path.localeCompare(b.path, "fr", { numeric: true }));
}
