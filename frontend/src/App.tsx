import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleHelp,
  Clapperboard,
  FolderOpen,
  KeyRound,
  Languages,
  Menu,
  Moon,
  Settings2,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import { ACCESS_KEY, api, message } from "./api";
import { activeStatuses, cn } from "./lib";
import type { Health, Job, Provider, Reanalysis } from "./types";
import { Button } from "./components/ui/button";
import { ErrorNotice, Logo, Spinner } from "./components/shared";
import { Explorer, LibraryTree } from "./components/explorer";
import { Translations } from "./components/translations";
import { Providers } from "./components/providers";

type Page = "explorer" | "translations" | "settings";
const getPage = (): Page =>
  (({ traductions: "translations", parametres: "settings" }) as const)[
    location.hash.slice(1) as "traductions"
  ] || "explorer";
const pages = [
  { id: "explorer", hash: "explorer", label: "Explorer", icon: FolderOpen },
  {
    id: "translations",
    hash: "traductions",
    label: "Traductions",
    icon: Languages,
  },
  { id: "settings", hash: "parametres", label: "Paramètres", icon: Settings2 },
] as const;

export default function App() {
  const client = useQueryClient();
  const [page, setPage] = useState<Page>(getPage);
  const [path, setPath] = useState("");
  const [reanalysis, setReanalysis] = useState<Reanalysis | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [locked, setLocked] = useState(false);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  const [theme, setTheme] = useState(
    () => localStorage.getItem("sillage.theme") || "dark",
  );
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<{ auth_required: boolean }>("/config"),
    retry: false,
  });
  const authenticated =
    !!config.data &&
    !locked &&
    (!config.data.auth_required || !!sessionStorage.getItem(ACCESS_KEY));
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/health"),
    enabled: authenticated,
    refetchInterval: 30_000,
  });
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () => api<Provider[]>("/providers"),
    enabled: authenticated,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    enabled: authenticated,
    refetchInterval: (query) =>
      query.state.data?.some((job) => activeStatuses.includes(job.status))
        ? 1500
        : 8000,
  });
  const notify = (text: string, error = false) => setToast({ text, error });
  const navigate = (target: Page) => {
    location.hash = pages.find((p) => p.id === target)!.hash;
    setMobileOpen(false);
  };
  useEffect(() => {
    const fn = () => setPage(getPage());
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sillage.theme", theme);
  }, [theme]);
  useEffect(() => {
    const fn = () => setLocked(true);
    window.addEventListener("sillage:unauthorized", fn);
    return () => window.removeEventListener("sillage:unauthorized", fn);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    document.title = `${pages.find((p) => p.id === page)?.label} · Sillage`;
  }, [page]);
  if (config.isPending)
    return (
      <div className="boot">
        <Logo />
        <Spinner>Ouverture de l’atelier…</Spinner>
      </div>
    );
  if (config.isError)
    return (
      <div className="boot">
        <Logo />
        <h1>Sillage</h1>
        <ErrorNotice
          error={`Le serveur est injoignable. ${message(config.error)}`}
          retry={() => void config.refetch()}
        />
      </div>
    );
  if (!authenticated)
    return (
      <AccessScreen
        onSuccess={() => {
          setLocked(false);
          void client.invalidateQueries();
        }}
        required={config.data?.auth_required ?? true}
      />
    );
  const running =
    jobs.data?.filter((j) => activeStatuses.includes(j.status)).length || 0;
  const toolMissing = health.data
    ? Object.entries(health.data.tools).filter(
        ([key, available]) => !available && ["ffmpeg", "ffprobe"].includes(key),
      )
    : [];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Aller au contenu
      </a>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Fermer la navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={cn("sidebar", mobileOpen && "is-open")}
        aria-label="Navigation principale"
      >
        <a className="brand" href="#explorer" aria-label="Sillage, Explorer">
          <Logo />
          <span>
            Sillage<span className="brand-sub">ATELIER DE SOUS-TITRES</span>
          </span>
        </a>
        <div className="sidebar-label">ESPACE DE TRAVAIL</div>
        <nav className="main-nav">
          {pages.map((p) => (
            <a
              key={p.id}
              href={`#${p.hash}`}
              onClick={() => setMobileOpen(false)}
              className={cn("nav-link", page === p.id && "active")}
              aria-current={page === p.id ? "page" : undefined}
            >
              <p.icon size={18} />
              <span>{p.label}</span>
              {p.id === "translations" && running > 0 && (
                <span className="nav-count">{running}</span>
              )}
            </a>
          ))}
        </nav>
        {page === "explorer" && (
          <div className="sidebar-library">
            <div className="sidebar-label">MÉDIATHÈQUE</div>
            <LibraryTree
              path={path}
              onNavigate={(p) => {
                setPath(p);
                setMobileOpen(false);
              }}
            />
          </div>
        )}
        <div className="sidebar-bottom">
          <div className="local-status">
            <span className={cn("server-dot", health.isError && "offline")} />
            <span>
              {health.isError ? "Serveur injoignable" : "Atelier local"}
              <small>
                {health.data ? `v${health.data.version}` : "Connexion…"}
              </small>
            </span>
            <ShieldCheck size={15} />
          </div>
          <div className="sidebar-tools">
            <Button
              variant="ghost"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={`Activer le thème ${theme === "dark" ? "clair" : "sombre"}`}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
              <span>Thème {theme === "dark" ? "sombre" : "clair"}</span>
            </Button>
            {config.data?.auth_required && (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Verrouiller l’atelier"
                onClick={() => {
                  sessionStorage.removeItem(ACCESS_KEY);
                  client.clear();
                  setLocked(true);
                }}
              >
                <KeyRound size={16} />
              </Button>
            )}
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="workspace-header">
          <div>
            <Button
              className="mobile-menu"
              variant="ghost"
              size="icon"
              aria-label="Ouvrir la navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={20} />
            </Button>
            <Clapperboard size={16} />
            <span>Mon atelier</span>
            <span className="header-slash">/</span>
            <strong>{pages.find((p) => p.id === page)?.label}</strong>
          </div>
          <span className="header-note">
            <span />
            Sous-titres, en toute maîtrise
          </span>
        </header>
        <main id="main-content" tabIndex={-1}>
          {health.isError && (
            <div className="global-notice">
              <ErrorNotice
                error="Connexion au serveur interrompue. Les opérations en cours continuent côté serveur."
                retry={() => {
                  void health.refetch();
                  void jobs.refetch();
                }}
              />
            </div>
          )}
          {toolMissing.length > 0 && (
            <div className="global-notice">
              <ErrorNotice
                error={`Outils multimédias indisponibles : ${toolMissing.map(([name]) => name).join(", ")}. Vérifiez l’installation du serveur.`}
              />
            </div>
          )}
          {
            <div hidden={page !== "explorer"}>
              <Explorer
                path={path}
                setPath={setPath}
                providers={providers.data || []}
                providersError={providers.error}
                notify={notify}
                onSettings={() => navigate("settings")}
                onJobs={() => navigate("translations")}
                reanalysis={reanalysis}
                onReanalysisConsumed={() => setReanalysis(null)}
              />
            </div>
          }
          {page === "translations" && (
            <Translations
              providers={providers.data || []}
              jobs={jobs.data || []}
              loading={jobs.isPending}
              error={jobs.error}
              retry={() => void jobs.refetch()}
              notify={notify}
              onExplore={() => navigate("explorer")}
              onReanalyzed={(result) => {
                setPath(result.episode.path.slice(0, result.episode.path.lastIndexOf("/")));
                setReanalysis(result);
                navigate("explorer");
              }}
            />
          )}
          {page === "settings" && (
            <Providers
              providers={providers.data || []}
              loading={providers.isPending}
              error={providers.error}
              retry={() => void providers.refetch()}
              health={health.data}
              notify={notify}
            />
          )}
        </main>
        <footer className="workspace-footer">
          <span>
            <ShieldCheck size={12} />
            Les fichiers MKV restent intacts
          </span>
          <span>
            Sillage <span className="footer-dot">·</span> Atelier personnel
          </span>
        </footer>
      </div>
      {toast && (
        <div
          className={cn("toast", toast.error && "toast-error")}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <CircleHelp size={17} /> : <Check size={17} />}
          <span>{toast.text}</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Fermer la notification"
            onClick={() => setToast(null)}
          >
            <X size={15} />
          </Button>
        </div>
      )}
    </div>
  );
}

function AccessScreen({
  onSuccess,
  required,
}: {
  onSuccess: () => void;
  required: boolean;
}) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="access-screen">
      <div className="access-card">
        <div className="access-brand">
          <Logo />
          Sillage
        </div>
        <div className="eyebrow">VOTRE ATELIER PERSONNEL</div>
        <h1>
          À chaque voix,
          <br />
          son sillage.
        </h1>
        <p>
          Saisissez la clé d’accès configurée sur votre serveur pour ouvrir la
          médiathèque.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            sessionStorage.setItem(ACCESS_KEY, key);
            try {
              await api("/providers");
              onSuccess();
            } catch (e) {
              sessionStorage.removeItem(ACCESS_KEY);
              setError(message(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="access-key">Clé d’accès</label>
          <div className="input-icon">
            <KeyRound size={16} />
            <input
              id="access-key"
              autoFocus
              type="password"
              autoComplete="current-password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required={required}
            />
          </div>
          {error && <ErrorNotice error={error} />}
          <Button type="submit" disabled={busy} className="access-submit">
            {busy ? "Vérification…" : "Ouvrir mon atelier"}
            <ArrowRight size={16} />
          </Button>
        </form>
        <small>
          <ShieldCheck size={14} />
          Clé conservée uniquement pour cette session.
        </small>
      </div>
      <div className="access-decoration" aria-hidden="true">
        <div>EN</div>
        <span />
        <div>FR</div>
      </div>
    </div>
  );
}
