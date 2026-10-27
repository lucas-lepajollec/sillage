import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpDown,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Clock3,
  FileVideo2,
  Eye,
  Folder,
  FolderOpen,
  HardDrive,
  Languages,
  ListFilter,
  Loader2,
  ScanLine,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Subtitles,
  X,
} from "lucide-react";
import { api, message } from "../api";
import {
  basename,
  canTranslate,
  cn,
  duration,
  language,
  preferredTrack,
  trackLabel,
} from "../lib";
import type { Browse, Episode, Job, Provider, Reanalysis, Scan, SyncMode } from "../types";
import { Button } from "./ui/button";
import { Empty, ErrorNotice, Modal, Spinner, StepHint } from "./shared";
import { PreviewDrawer } from "./preview";
import { TrackSelection } from "./track-selection";

export function LibraryTree({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate: (path: string) => void;
}) {
  const query = useQuery({
    queryKey: ["browse", ""],
    queryFn: () => api<Browse>("/browse"),
  });
  if (query.isPending)
    return (
      <div className="tree-loading">
        <Loader2 size={14} className="spin" />
        Connexion aux médias…
      </div>
    );
  if (query.isError)
    return (
      <div className="tree-error">
        Médiathèque inaccessible.
        <button onClick={() => void query.refetch()}>Réessayer</button>
      </div>
    );
  return (
    <div className="library-tree">
      {query.data.roots.map((root, index) => (
        <DirectoryNode
          key={root}
          path={root}
          name={basename(root)}
          current={path || query.data.path}
          onNavigate={onNavigate}
          root
          initialOpen={index === 0}
        />
      ))}
    </div>
  );
}

function DirectoryNode({
  path,
  name,
  current,
  onNavigate,
  root = false,
  initialOpen = false,
}: {
  path: string;
  name: string;
  current: string;
  onNavigate: (path: string) => void;
  root?: boolean;
  initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);
  const query = useQuery({
    queryKey: ["browse", path],
    queryFn: () => api<Browse>(`/browse?path=${encodeURIComponent(path)}`),
    enabled: open,
  });
  return (
    <div className="tree-node">
      <div className={cn("tree-row", path === current && "current")}>
        <button
          className="tree-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={`${open ? "Replier" : "Déplier"} ${name}`}
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
        <button
          className="tree-name"
          onClick={() => onNavigate(path)}
          title={path}
        >
          {root ? (
            <HardDrive size={15} />
          ) : open ? (
            <FolderOpen size={15} />
          ) : (
            <Folder size={15} />
          )}
          <span>{name}</span>
        </button>
      </div>
      {open && (
        <div className="tree-children">
          {query.isPending && <span className="tree-loading">Chargement…</span>}
          {query.isError && (
            <button className="tree-error" onClick={() => void query.refetch()}>
              Réessayer le chargement
            </button>
          )}
          {query.data?.directories.map((dir) => (
            <DirectoryNode
              key={dir.path}
              path={dir.path}
              name={dir.name}
              current={current}
              onNavigate={onNavigate}
            />
          ))}
          {query.data && query.data.directories.length === 0 && (
            <span className="tree-empty">Aucun sous-dossier</span>
          )}
        </div>
      )}
    </div>
  );
}

type Filters = {
  language: string;
  format: string;
  status: string;
  hideFrench: boolean;
};
const defaultFilters: Filters = {
  language: "",
  format: "",
  status: "",
  hideFrench: false,
};
const readFilters = (): Filters => {
  try {
    return {
      ...defaultFilters,
      ...JSON.parse(localStorage.getItem("sillage.filters") || "{}"),
    };
  } catch {
    return defaultFilters;
  }
};
const episodeStatus = (episode: Episode) =>
  episode.error
    ? "error"
    : episode.has_french
      ? "french"
      : !canTranslate(episode)
        ? "unsupported"
        : !episode.tracks.some(
              (t) =>
                t.supported && ["eng", "en"].includes(t.language.toLowerCase()),
            )
          ? "choose"
          : "ready";
const statusLabels: Record<string, string> = {
  error: "Erreur d’analyse",
  french: "Français présent",
  unsupported: "Sans source texte",
  choose: "Source à vérifier",
  ready: "Prêt à traduire",
};

export function Explorer({
  path,
  setPath,
  providers,
  providersError,
  notify,
  onSettings,
  onJobs,
  reanalysis,
  onReanalysisConsumed,
}: {
  path: string;
  setPath: (path: string) => void;
  providers: Provider[];
  providersError: unknown;
  notify: (text: string, error?: boolean) => void;
  onSettings: () => void;
  onJobs: () => void;
  reanalysis: Reanalysis | null;
  onReanalysisConsumed: () => void;
}) {
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [filters, setFilters] = useState<Filters>(readFilters);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([
    { id: "name", desc: false },
  ]);
  const [tracks, setTracks] = useState<Record<string, string>>({});
  const [detail, setDetail] = useState<Episode | null>(null);
  const [trackSelection, setTrackSelection] = useState<{ initial?: Episode } | null>(null);
  const [providerId, setProviderId] = useState("");
  const [syncMode, setSyncMode] = useState<SyncMode>("preserve");
  const [offset, setOffset] = useState(0);
  const [syncOpen, setSyncOpen] = useState(false);
  const [confirmFrench, setConfirmFrench] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [inspected, setInspected] = useState<{ path: string; data: Scan } | null>(null);
  const browse = useQuery({
    queryKey: ["browse", path],
    queryFn: () => api<Browse>(`/browse?path=${encodeURIComponent(path)}`),
  });
  const currentPath = browse.data?.path || path;
  const scan = useMutation({
    mutationFn: (body: { path: string; recursive: boolean }) =>
      api<Scan>("/scan", body),
    onSuccess: (data) => {
      setInspected(null);
      setSelection({});
      setTracks({});
      if (data.errors.length)
        notify(
          `${data.errors.length} fichier(s) n’ont pas pu être analysés.`,
          true,
        );
    },
    onError: (e) => notify(message(e), true),
  });
  const scanned =
    inspected?.path === currentPath ? inspected.data :
      scan.data && scan.variables?.path === currentPath ? scan.data : undefined;
  const episodes = scanned?.episodes || [];
  const selectedProvider =
    providers.find((p) => p.id === providerId) || providers[0];
  const create = useMutation({
    mutationFn: (items: { path: string; track_id: string }[]) =>
      api<Job[]>("/jobs", {
        items,
        provider_id: selectedProvider?.id,
        sync_mode: syncMode,
        offset_ms: syncMode === "offset" ? offset : 0,
      }),
    onSuccess: (jobs) => {
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setSelection({});
      setConfirmFrench(false);
      notify(
        `${jobs.length} traduction${jobs.length > 1 ? "s" : ""} ajoutée${jobs.length > 1 ? "s" : ""} à la file.`,
      );
      onJobs();
    },
    onError: (e) => notify(message(e), true),
  });
  useEffect(() => {
    setSelection({});
    setSearch("");
    setDetail(null);
    setTrackSelection(null);
    setInspected(null);
  }, [path]);
  useEffect(() => {
    if (!reanalysis) return;
    scan.reset();
    const { episode, job } = reanalysis;
    const folder = episode.path.slice(0, episode.path.lastIndexOf("/"));
    setInspected({ path: folder, data: { episodes: [episode], errors: [] } });
    setSelection(canTranslate(episode) ? { [episode.path]: true } : {});
    const sameTrack = episode.tracks.some((t) => t.id === job.track_id && t.supported);
    setTracks(sameTrack ? { [episode.path]: job.track_id } : {});
    setFilters(defaultFilters);
    setDetail(episode);
    setProviderId(job.provider_id);
    setSyncMode(job.sync_mode);
    setOffset(job.offset_ms);
    notify(sameTrack ? "Source réanalysée sans appel à l’IA. L’ancien traitement et ses checkpoints sont conservés." : "L’ancienne piste n’est plus disponible. Vérifiez le nouveau choix avant de traduire.");
    onReanalysisConsumed();
  }, [reanalysis]);
  useEffect(() => {
    localStorage.setItem("sillage.filters", JSON.stringify(filters));
  }, [filters]);
  const filtered = useMemo(
    () =>
      episodes.filter((e) => {
        const needle = search.toLocaleLowerCase("fr");
        return (
          (!needle ||
            `${e.name} ${e.path}`.toLocaleLowerCase("fr").includes(needle)) &&
          (!filters.language ||
            e.tracks.some((t) => t.language === filters.language)) &&
          (!filters.format ||
            e.tracks.some((t) => t.format === filters.format)) &&
          (!filters.status || episodeStatus(e) === filters.status) &&
          (!filters.hideFrench || !e.has_french)
        );
      }),
    [episodes, search, filters],
  );
  const changeTrack = (episode: Episode, track: string) =>
    setTracks((old) => ({ ...old, [episode.path]: track }));
  // TanStack selection/sorting pattern adapted from shadcn-admin TasksTable (MIT).
  const columns: ColumnDef<Episode>[] = [
    {
      id: "select",
      header: ({ table }) => (
        <input
          type="checkbox"
          aria-label="Sélectionner tous les épisodes filtrés"
          checked={table.getIsAllRowsSelected()}
          ref={(input) => {
            if (input) input.indeterminate = table.getIsSomeRowsSelected();
          }}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          aria-label={`Sélectionner ${row.original.name}`}
          checked={row.getIsSelected()}
          disabled={!row.getCanSelect()}
          onChange={row.getToggleSelectedHandler()}
        />
      ),
    },
    {
      accessorKey: "name",
      header: ({ column }) => (
        <button
          className="column-sort"
          onClick={() => column.toggleSorting()}
          aria-label="Trier par nom"
        >
          Fichier
          {column.getIsSorted() === "asc" ? (
            <ArrowUp size={12} />
          ) : column.getIsSorted() === "desc" ? (
            <ArrowDown size={12} />
          ) : (
            <ArrowUpDown size={12} />
          )}
        </button>
      ),
      cell: ({ row }) => (
        <button
          className="episode-name"
          onClick={() => setDetail(row.original)}
          title={row.original.path}
        >
          <span className="file-icon">
            <FileVideo2 size={19} />
          </span>
          <span>
            <strong>{row.original.name}</strong>
            <small>
              {row.original.path
                .slice(0, -row.original.name.length)
                .replace(/\/$/, "")}
            </small>
          </span>
        </button>
      ),
    },
    {
      accessorKey: "duration",
      header: ({ column }) => (
        <button className="column-sort" onClick={() => column.toggleSorting()}>
          Durée
          <ArrowUpDown size={12} />
        </button>
      ),
      cell: ({ row }) => (
        <span className="duration-cell">
          {row.original.duration ? duration(row.original.duration) : "—"}
        </span>
      ),
    },
    {
      id: "track",
      header: "Piste source",
      cell: ({ row }) => {
        const e = row.original;
        const selected = tracks[e.path] || preferredTrack(e)?.id || "";
        return e.tracks.length ? (
          <div className="track-select">
            <select
              aria-label={`Piste source de ${e.name}`}
              value={selected}
              onChange={(event) => changeTrack(e, event.target.value)}
            >
              <option value="" disabled>
                Choisir une piste
              </option>
              {e.tracks.map((t) => (
                <option key={t.id} value={t.id} disabled={!t.supported}>
                  {trackLabel(t)}
                  {!t.supported ? " · graphique, non traduit" : ""}
                </option>
              ))}
            </select>
            <ChevronDown size={12} />
            <span className="track-count">
              {tracks[e.path] ? "Votre choix" : "Choix automatique"} · {e.tracks.length} piste{e.tracks.length > 1 ? "s" : ""}
              {e.tracks.some((t) => t.external) ? " · externe incluse" : ""}
            </span>
            <button className="track-preview-link" onClick={() => setDetail(e)} aria-label={`Vérifier la piste de ${e.name}`}>
              <Eye size={12} />Vérifier la piste
            </button>
          </div>
        ) : (
          <span className="muted">Aucun sous-titre</span>
        );
      },
    },
    {
      id: "status",
      header: "État",
      cell: ({ row }) => (
        <span
          className={cn(
            "episode-status",
            `episode-${episodeStatus(row.original)}`,
          )}
        >
          {episodeStatus(row.original) === "french" ? (
            <Check size={13} />
          ) : (
            <span className="status-dot" />
          )}
          {statusLabels[episodeStatus(row.original)]}
        </span>
      ),
    },
    {
      id: "detail",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Détails de ${row.original.name}`}
          onClick={() => setDetail(row.original)}
        >
          <ChevronRight size={16} />
        </Button>
      ),
    },
  ];
  const table = useReactTable({
    data: filtered,
    columns,
    getRowId: (row) => row.path,
    state: { rowSelection: selection, sorting },
    onRowSelectionChange: setSelection,
    onSortingChange: setSorting,
    enableRowSelection: (row) => canTranslate(row.original),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 25 } },
  });
  const selected = episodes.filter((e) => selection[e.path] && canTranslate(e));
  const filterCount = Object.values(filters).filter(Boolean).length;
  const translate = () =>
    create.mutate(
      selected.map((e) => ({
        path: e.path,
        track_id: tracks[e.path] || preferredTrack(e)!.id,
      })),
    );
  const start = () =>
    selected.some((e) => e.has_french) ? setConfirmFrench(true) : translate();
  const directories =
    browse.data?.directories.filter(
      (dir) =>
        !search ||
        dir.name
          .toLocaleLowerCase("fr")
          .includes(search.toLocaleLowerCase("fr")),
    ) || [];
  const root =
    browse.data?.roots.find(
      (r) => currentPath === r || currentPath.startsWith(`${r}/`),
    ) || "";
  const relativeParts = currentPath
    .slice(root.length)
    .split("/")
    .filter(Boolean);
  return (
    <div
      className={cn(
        "page explorer-page",
        selected.length > 0 && "has-selection",
      )}
    >
      <div className="page-heading">
        <div>
          <div className="eyebrow">VOTRE MÉDIATHÈQUE</div>
          <h1>Explorer</h1>
          <p>Choisissez les épisodes. Donnez-leur une voix française.</p>
        </div>
        <StepHint />
      </div>
      <section className="explorer-surface" aria-label="Explorateur de médias">
        <div className="location-bar">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Dossier parent"
            disabled={!browse.data?.parent}
            onClick={() => browse.data?.parent && setPath(browse.data.parent)}
          >
            <ChevronLeft size={17} />
          </Button>
          <nav className="breadcrumbs" aria-label="Fil d’Ariane">
            <button onClick={() => setPath(root)}>
              <HardDrive size={15} />
              <span>{basename(root) || "Médias"}</span>
            </button>
            {relativeParts.map((part, i) => (
              <span key={i}>
                <ChevronRight size={12} />
                <button
                  aria-current={
                    i === relativeParts.length - 1 ? "location" : undefined
                  }
                  onClick={() =>
                    setPath(
                      `${root}/${relativeParts.slice(0, i + 1).join("/")}`,
                    )
                  }
                >
                  {part}
                </button>
              </span>
            ))}
          </nav>
          <span className="path-label" title={currentPath}>
            {currentPath}
          </span>
        </div>
        <div className="explorer-toolbar">
          <div className="input-icon search-input">
            <Search size={16} />
            <input
              aria-label="Rechercher un fichier ou un dossier"
              placeholder={
                scanned
                  ? "Rechercher dans les résultats…"
                  : "Rechercher un dossier…"
              }
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                className="input-clear"
                aria-label="Effacer la recherche"
                onClick={() => setSearch("")}
              >
                <X size={13} />
              </button>
            )}
          </div>
          <label className="recursive-toggle">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(e) => setRecursive(e.target.checked)}
            />
            <span>Sous-dossiers inclus</span>
          </label>
          <Button
            onClick={() => scan.mutate({ path: currentPath, recursive })}
            disabled={scan.isPending || !browse.data}
            data-testid="scan-button"
          >
            {scan.isPending ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <ScanLine size={16} />
            )}
            {scan.isPending ? "Analyse en cours…" : "Scanner le dossier"}
          </Button>
        </div>
        {browse.isPending && <Spinner>Ouverture du dossier…</Spinner>}
        {browse.isError && (
          <div className="inset-notice">
            <ErrorNotice
              error={message(browse.error)}
              retry={() => void browse.refetch()}
            />
          </div>
        )}
        {browse.data && directories.length > 0 && (
          <div className="folder-list">
            {directories.map((dir) => (
              <button
                className="folder-item"
                key={dir.path}
                onClick={() => setPath(dir.path)}
              >
                <Folder size={20} />
                <span>{dir.name}</span>
                <ChevronRight size={14} />
              </button>
            ))}
          </div>
        )}
        {scan.isPending && (
          <div className="scan-loading">
            <div className="scan-line-art">
              <ScanLine size={30} />
            </div>
            <h3>Lecture des pistes de sous-titres</h3>
            <p>Les MKV sont inspectés, sans extraction ni modification.</p>
            <div className="skeleton-rows">
              {[0, 1, 2].map((i) => (
                <div key={i}>
                  <span />
                  <span />
                  <span />
                </div>
              ))}
            </div>
          </div>
        )}
        {scan.isError && (
          <div className="inset-notice">
            <ErrorNotice
              error={message(scan.error)}
              retry={() => scan.mutate({ path: currentPath, recursive })}
            />
          </div>
        )}
        {!scan.isPending &&
          !scanned &&
          !browse.isPending &&
          !browse.isError && (
            <Empty
              icon={<Subtitles size={30} />}
              title={
                directories.length
                  ? "Votre prochaine traduction commence ici."
                  : "Un dossier, une nouvelle langue."
              }
              action={
                <Button
                  variant="outline"
                  onClick={() => scan.mutate({ path: currentPath, recursive })}
                >
                  <ScanLine size={15} />
                  Analyser les fichiers MKV
                  <ArrowRight size={14} />
                </Button>
              }
            >
              Naviguez dans vos dossiers, puis lancez un scan pour découvrir les
              pistes disponibles.
              {browse.data && browse.data.files.length > 0
                ? ` ${browse.data.files.length} fichier(s) dans ce dossier.`
                : ""}
            </Empty>
          )}
        {!scan.isPending && scanned && (
          <>
            <div className="results-heading">
              <div>
                <span className="section-label">{inspected ? "ÉPISODE RÉANALYSÉ" : "RÉSULTATS DU SCAN"}</span>
                <strong>
                  {episodes.length} épisode{episodes.length > 1 ? "s" : ""}
                </strong>
                <span className="results-divider" />
                <span>
                  {episodes.filter((e) => e.has_french).length} avec du français
                </span>
              </div>
              <button
                className={cn("filter-button", filterCount > 0 && "active")}
                onClick={() => setFilterOpen(!filterOpen)}
                aria-expanded={filterOpen}
              >
                <ListFilter size={14} />
                Filtres{filterCount > 0 && <span>{filterCount}</span>}
                <ChevronDown size={12} />
              </button>
            </div>
            {episodes.length > 0 && <div className="source-selection-toolbar">
              <div><strong>Pistes source</strong><small>Vérifiez chaque épisode ou appliquez votre choix en groupe.</small></div>
              <Button variant="outline" onClick={() => setTrackSelection({})}>
                <Subtitles size={15} />Choisir les pistes
              </Button>
            </div>}
            {inspected && <p className="reanalysis-notice">L’ancien traitement et ses checkpoints sont conservés. Une nouvelle traduction ne remplace jamais un sous-titre déjà exporté. Pour analyser les autres épisodes, utilisez « Scanner le dossier ».</p>}
            {(filterOpen || filterCount > 0) && (
              <div className="filters" aria-label="Filtres des épisodes">
                <label>
                  <span>Langue</span>
                  <select
                    value={filters.language}
                    onChange={(e) =>
                      setFilters((f) => ({ ...f, language: e.target.value }))
                    }
                  >
                    <option value="">Toutes les langues</option>
                    {[
                      ...new Set(
                        episodes.flatMap((e) =>
                          e.tracks.map((t) => t.language),
                        ),
                      ),
                    ].map((lang) => (
                      <option key={lang} value={lang}>
                        {language(lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Format</span>
                  <select
                    value={filters.format}
                    onChange={(e) =>
                      setFilters((f) => ({ ...f, format: e.target.value }))
                    }
                  >
                    <option value="">Tous les formats</option>
                    {[
                      ...new Set(
                        episodes.flatMap((e) => e.tracks.map((t) => t.format)),
                      ),
                    ].map((format) => (
                      <option key={format} value={format}>
                        {format.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>État</span>
                  <select
                    value={filters.status}
                    onChange={(e) =>
                      setFilters((f) => ({ ...f, status: e.target.value }))
                    }
                  >
                    <option value="">Tous les états</option>
                    {Object.entries(statusLabels).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={filters.hideFrench}
                    onChange={(e) =>
                      setFilters((f) => ({
                        ...f,
                        hideFrench: e.target.checked,
                      }))
                    }
                  />
                  Sans français uniquement
                </label>
                {filterCount > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setFilters(defaultFilters)}
                  >
                    Réinitialiser
                    <X size={12} />
                  </Button>
                )}
              </div>
            )}
            {scanned.errors.length > 0 && (
              <details className="scan-errors">
                <summary>
                  {scanned.errors.length} erreur(s) pendant l’analyse
                </summary>
                {scanned.errors.map((e) => (
                  <p key={e.path}>
                    <strong>{e.path}</strong> — {e.error}
                  </p>
                ))}
              </details>
            )}
            {episodes.length === 0 ? (
              <Empty
                icon={<FileVideo2 size={28} />}
                title="Aucun épisode MKV trouvé"
              >
                Vérifiez ce dossier et l’option « Sous-dossiers inclus », puis
                relancez le scan.
              </Empty>
            ) : filtered.length === 0 ? (
              <Empty
                icon={<Search size={26} />}
                title="Aucun épisode ne correspond"
              >
                Modifiez votre recherche ou réinitialisez les filtres.
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSearch("");
                    setFilters(defaultFilters);
                  }}
                >
                  Effacer les filtres
                </Button>
              </Empty>
            ) : (
              <>
                <div className="episode-table-wrap">
                  <table className="episode-table">
                    <thead>
                      {table.getHeaderGroups().map((group) => (
                        <tr key={group.id}>
                          {group.headers.map((header) => (
                            <th key={header.id} scope="col">
                              {flexRender(
                                header.column.columnDef.header,
                                header.getContext(),
                              )}
                            </th>
                          ))}
                        </tr>
                      ))}
                    </thead>
                    <tbody>
                      {table.getRowModel().rows.map((row) => (
                        <tr
                          key={row.id}
                          className={cn(row.getIsSelected() && "selected")}
                          data-state={
                            row.getIsSelected() ? "selected" : undefined
                          }
                        >
                          {row.getVisibleCells().map((cell) => (
                            <td key={cell.id}>
                              {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext(),
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="table-footer">
                  <span>
                    {selected.length
                      ? `${selected.length} sélectionné${selected.length > 1 ? "s" : ""}`
                      : "Sélectionnez les épisodes à traduire"}
                    <span className="footer-dot">·</span>
                    {filtered.length} résultat{filtered.length > 1 ? "s" : ""}
                  </span>
                  <div>
                    <label className="page-size">
                      <span>Par page</span>
                      <select
                        aria-label="Nombre de lignes par page"
                        value={table.getState().pagination.pageSize}
                        onChange={(e) =>
                          table.setPageSize(Number(e.target.value))
                        }
                      >
                        {[25, 50, 100].map((n) => (
                          <option key={n}>{n}</option>
                        ))}
                      </select>
                    </label>
                    <span>
                      {table.getState().pagination.pageIndex + 1} /{" "}
                      {table.getPageCount()}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Page précédente"
                      disabled={!table.getCanPreviousPage()}
                      onClick={() => table.previousPage()}
                    >
                      <ChevronLeft size={15} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Page suivante"
                      disabled={!table.getCanNextPage()}
                      onClick={() => table.nextPage()}
                    >
                      <ChevronRight size={15} />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </section>
      <div className="explorer-reassurance">
        <span>
          <ShieldCheck size={14} />
          Vos originaux restent intacts.
        </span>
        <span>
          <Clock3 size={14} />
          Timings source conservés par défaut.
        </span>
        <span>
          <Subtitles size={14} />
          Export .fr.ass ou .fr.srt à côté du MKV.
        </span>
      </div>
      {selected.length > 0 && (
        <div className="selection-bar">
          <div className="selection-count">
            <span>{selected.length}</span>
            <div>
              épisode{selected.length > 1 ? "s" : ""} sélectionné
              {selected.length > 1 ? "s" : ""}
              <button onClick={() => setSelection({})}>
                Tout désélectionner
              </button>
            </div>
          </div>
          <div className="selection-provider">
            {providers.length > 0 ? (
              <>
                <label htmlFor="selected-provider">TRADUIRE AVEC</label>
                <select
                  id="selected-provider"
                  value={selectedProvider?.id}
                  onChange={(e) => setProviderId(e.target.value)}
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.model}
                    </option>
                  ))}
                </select>
                <ChevronsUpDown size={13} />
              </>
            ) : (
              <Button variant="outline" onClick={onSettings}>
                <Settings2 size={15} />
                {providersError
                  ? "Vérifier les providers"
                  : "Configurer un provider"}
              </Button>
            )}
          </div>
          <Button
            className="sync-trigger"
            variant="ghost"
            onClick={() => setSyncOpen(true)}
            title="Options de synchronisation"
          >
            <SlidersHorizontal size={16} />
            <span>
              {syncMode === "preserve"
                ? "Timings source"
                : syncMode === "offset"
                  ? `${offset > 0 ? "+" : ""}${offset} ms`
                  : "Sync. automatique"}
            </span>
          </Button>
          <Button
            onClick={start}
            disabled={!selectedProvider || create.isPending}
          >
            {create.isPending ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <Languages size={16} />
            )}
            Traduire
            <ArrowRight size={15} />
          </Button>
        </div>
      )}
      <PreviewDrawer
        episode={detail}
        open={!!detail}
        onClose={() => setDetail(null)}
        trackId={
          detail ? tracks[detail.path] || preferredTrack(detail)?.id : undefined
        }
        onTrackChange={(id) => detail && changeTrack(detail, id)}
        trackSelectionMode={detail && tracks[detail.path] ? "manual" : "auto"}
        onTrackReset={() => detail && setTracks((old) => {
          const next = { ...old };
          delete next[detail.path];
          return next;
        })}
        onApplyToGroup={() => {
          if (detail) setTrackSelection({ initial: detail });
          setDetail(null);
        }}
        notify={notify}
      />
      {trackSelection && <TrackSelection
        episodes={episodes} selected={selected} tracks={tracks} initial={trackSelection.initial}
        onClose={() => setTrackSelection(null)}
        onApply={(changes) => {
          setTracks((old) => {
            const next = { ...old };
            for (const [path, id] of Object.entries(changes)) {
              if (id) next[path] = id;
              else delete next[path];
            }
            return next;
          });
          setTrackSelection(null);
          notify(`Choix de piste appliqué à ${Object.keys(changes).length} épisode(s).`);
        }}
      />}
      <Modal
        open={syncOpen}
        onOpenChange={setSyncOpen}
        title="Synchronisation"
        description="La traduction conserve les timestamps. Choisissez une correction seulement si la source est décalée."
      >
        <div className="sync-options">
          {(
            [
              {
                value: "preserve",
                title: "Conserver les timings source",
                detail: "Aucun changement de timestamp. Option recommandée.",
                icon: ShieldCheck,
              },
              {
                value: "offset",
                title: "Appliquer un décalage manuel",
                detail: "Un offset constant sur tous les événements.",
                icon: Clock3,
              },
              {
                value: "auto",
                title: "Proposer une correction automatique",
                detail:
                  "Analyse audio, puis validation explicite avant export.",
                icon: Sparkles,
              },
            ] as const
          ).map((option) => (
            <label
              className={cn(
                "sync-option",
                syncMode === option.value && "chosen",
              )}
              key={option.value}
            >
              <input
                type="radio"
                name="sync"
                value={option.value}
                checked={syncMode === option.value}
                onChange={() => setSyncMode(option.value)}
              />
              <option.icon size={18} />
              <span>
                <strong>{option.title}</strong>
                <small>{option.detail}</small>
              </span>
            </label>
          ))}
        </div>
        {syncMode === "offset" && (
          <label className="offset-field">
            Décalage en millisecondes
            <input
              type="number"
              min={-600000}
              max={600000}
              step={50}
              value={offset}
              onChange={(e) => setOffset(Number(e.target.value))}
            />
            <small>
              Positif : afficher plus tard. Négatif : afficher plus tôt.
            </small>
          </label>
        )}
        {syncMode === "auto" && (
          <p className="notice">
            <Sparkles size={16} />
            Le résultat attendra dans « À vérifier ». Vous pourrez comparer puis
            accepter la proposition, ou conserver les timings d’origine.
          </p>
        )}
        <div className="modal-footer">
          <Button onClick={() => setSyncOpen(false)}>
            Appliquer aux épisodes sélectionnés
            <Check size={15} />
          </Button>
        </div>
      </Modal>
      <Modal
        open={confirmFrench}
        onOpenChange={setConfirmFrench}
        title="Du français est déjà présent"
        description="Au moins un épisode sélectionné contient une piste française. Les originaux et les sous-titres existants seront conservés."
      >
        <p className="modal-body-copy">
          Le serveur refusera de remplacer un fichier de sortie existant.
          Vérifiez vos pistes avant de continuer.
        </p>
        <div className="modal-footer">
          <Button variant="outline" onClick={() => setConfirmFrench(false)}>
            Retour à la sélection
          </Button>
          <Button onClick={translate} disabled={create.isPending}>
            {create.isPending ? "Création…" : "Créer les traductions"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
