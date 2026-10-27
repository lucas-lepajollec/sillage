import type { Episode, Track } from "./types";

const normalized = (text: string) => text.normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");
const canonicalLanguage = (code: string) => {
  const value = normalized(code);
  return ({ eng: "en", fra: "fr", fre: "fr", jpn: "ja" })[value as "eng"] || value;
};
export const parentFolder = (path: string) => path.slice(0, path.lastIndexOf("/"));

// Stream indices and filenames are local to a container, never a group rule.
export function matchSourceTrack(episode: Episode, reference: Track): { track?: Track; reason?: string } {
  const candidates = episode.tracks.filter((track) =>
    track.supported &&
    canonicalLanguage(track.language) === canonicalLanguage(reference.language) &&
    normalized(track.format) === normalized(reference.format) &&
    track.external === reference.external &&
    track.forced === reference.forced && track.sdh === reference.sdh &&
    // External filenames vary by episode and cannot identify equivalent tracks.
    (track.external || normalized(track.title) === normalized(reference.title)),
  );
  if (candidates.length === 1) return { track: candidates[0] };
  return { reason: candidates.length ? "Plusieurs pistes correspondent : choisissez pour cet épisode." : "Aucune piste équivalente : choix actuel conservé." };
}
