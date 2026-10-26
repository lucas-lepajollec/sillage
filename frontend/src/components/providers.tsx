import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Cpu,
  FlaskConical,
  Globe2,
  KeyRound,
  Languages,
  Loader2,
  Pencil,
  Plus,
  Server,
  Settings2,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { api, message } from "../api";
import { cn } from "../lib";
import type { Health, Provider, ProviderKind } from "../types";
import { Button } from "./ui/button";
import { Empty, ErrorNotice, Modal, Spinner } from "./shared";

const kinds: { id: ProviderKind; label: string; base: string }[] = [
  { id: "openai", label: "OpenAI", base: "https://api.openai.com/v1" },
  { id: "anthropic", label: "Anthropic", base: "https://api.anthropic.com/v1" },
  {
    id: "gemini",
    label: "Google Gemini",
    base: "https://generativelanguage.googleapis.com/v1beta",
  },
  { id: "deepseek", label: "DeepSeek", base: "https://api.deepseek.com" },
  {
    id: "openrouter",
    label: "OpenRouter",
    base: "https://openrouter.ai/api/v1",
  },
  { id: "ollama", label: "Ollama", base: "" },
  { id: "custom", label: "OpenAI compatible", base: "" },
];
const emptyProvider = (): Provider => ({
  name: "",
  kind: "openai",
  base_url: kinds[0].base,
  model: "",
  temperature: null,
  batch_size: 30,
  concurrency: 1,
  timeout: 90,
  retries: 3,
  source_language: "en",
  target_language: "fr",
  glossary: "",
});

export function Providers({
  providers,
  loading,
  error,
  retry,
  health,
  notify,
}: {
  providers: Provider[];
  loading: boolean;
  error: unknown;
  retry: () => void;
  health?: Health;
  notify: (text: string, error?: boolean) => void;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<Provider | null>(null);
  const [deleting, setDeleting] = useState<Provider | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, { ok: boolean; text: string }>
  >({});
  const [testId, setTestId] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/providers/${encodeURIComponent(id)}`, undefined, "DELETE"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["providers"] });
      setDeleting(null);
      notify("Profil supprimé.");
    },
    onError: (e) => notify(message(e), true),
  });
  const test = async (provider: Provider) => {
    const id = provider.id!;
    setTestId(id);
    setTestResults((results) => {
      const next = { ...results };
      delete next[id];
      return next;
    });
    try {
      const result = await api<{ ok: boolean; message: string }>(
        `/providers/${encodeURIComponent(id)}/test`,
        {},
      );
      setTestResults((old) => ({
        ...old,
        [id]: { ok: result.ok, text: result.message },
      }));
      notify(result.message, !result.ok);
    } catch (e) {
      setTestResults((old) => ({
        ...old,
        [id]: { ok: false, text: message(e) },
      }));
      notify(message(e), true);
    } finally {
      setTestId(null);
    }
  };
  return (
    <div className="page settings-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">UN ATELIER À VOTRE MESURE</div>
          <h1>Paramètres</h1>
          <p>Vos modèles, vos langues, vos mots.</p>
        </div>
        <Button onClick={() => setEditing(emptyProvider())}>
          <Plus size={16} />
          Ajouter un provider
        </Button>
      </div>
      <section className="settings-section">
        <div className="settings-section-heading">
          <div>
            <h2>
              <Cpu size={18} />
              Providers de traduction
            </h2>
            <p>
              Un profil associe un service, un modèle et un glossaire. Utilisez
              un profil par série si nécessaire.
            </p>
          </div>
          <span className="subtle-count">
            {providers.length} configuré{providers.length > 1 ? "s" : ""}
          </span>
        </div>
        {loading && <Spinner>Chargement des providers…</Spinner>}
        {!!error && <ErrorNotice error={message(error)} retry={retry} />}
        {!loading && !error && providers.length === 0 && (
          <div className="provider-empty">
            <Empty
              icon={<Cpu size={31} />}
              title="Le bon modèle, pour les bons mots."
              action={
                <Button
                  variant="outline"
                  onClick={() => setEditing(emptyProvider())}
                >
                  <Plus size={15} />
                  Configurer mon premier provider
                  <ArrowRight size={14} />
                </Button>
              }
            >
              Connectez une API cloud ou votre serveur Ollama. Choisissez
              librement le modèle, sans liste imposée.
            </Empty>
            <div className="provider-types">
              <span>OpenAI</span>
              <span>Anthropic</span>
              <span>Gemini</span>
              <span>DeepSeek</span>
              <span>OpenRouter</span>
              <span>Ollama</span>
              <span>OpenAI compatible</span>
            </div>
          </div>
        )}
        <div className="provider-list">
          {providers.map((provider) => (
            <article className="provider-card" key={provider.id}>
              <div className="provider-main">
                <span
                  className={cn(
                    "provider-icon",
                    provider.kind === "ollama" && "local",
                  )}
                >
                  {provider.kind === "ollama" ? (
                    <Server size={21} />
                  ) : (
                    <Cpu size={21} />
                  )}
                </span>
                <div className="provider-title">
                  <h3>{provider.name}</h3>
                  <p>
                    {kinds.find((k) => k.id === provider.kind)?.label}
                    <span className="footer-dot">·</span>
                    <code>{provider.model}</code>
                  </p>
                </div>
                <div className="provider-card-actions">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Modifier ${provider.name}`}
                    onClick={() => setEditing({ ...provider, api_key: "" })}
                  >
                    <Pencil size={15} />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Supprimer ${provider.name}`}
                    onClick={() => setDeleting(provider)}
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              </div>
              <div className="provider-properties">
                <span>
                  <Languages size={13} />
                  {provider.source_language.toUpperCase()}
                  <ArrowRight size={11} />
                  {provider.target_language.toUpperCase()}
                </span>
                <span>
                  <KeyRound size={13} />
                  {provider.has_key
                    ? "Clé enregistrée"
                    : provider.kind === "ollama"
                      ? "Serveur local"
                      : "Sans clé"}
                </span>
                <span>{provider.batch_size} segments / lot</span>
                {provider.glossary && (
                  <span>
                    <BookOpen size={13} />
                    Glossaire personnalisé
                  </span>
                )}
              </div>
              <div className="provider-card-footer">
                <span className="provider-url" title={provider.base_url}>
                  <Globe2 size={12} />
                  {provider.base_url || "URL du service par défaut"}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void test(provider)}
                  disabled={!!testId}
                >
                  {testId === provider.id ? (
                    <Loader2 size={14} className="spin" />
                  ) : (
                    <FlaskConical size={14} />
                  )}
                  {testId === provider.id
                    ? "Connexion…"
                    : "Tester la connexion"}
                </Button>
              </div>
              {testResults[provider.id!] && (
                <div
                  className={cn(
                    "provider-test-result",
                    !testResults[provider.id!].ok && "test-failed",
                  )}
                  role="status"
                >
                  {testResults[provider.id!].ok ? (
                    <CheckCircle2 size={14} />
                  ) : (
                    <Circle size={14} />
                  )}
                  {testResults[provider.id!].text}
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
      <section className="settings-section system-section">
        <div className="settings-section-heading">
          <div>
            <h2>
              <Settings2 size={18} />
              Environnement de traitement
            </h2>
            <p>
              Les outils sont fournis par le serveur. Les fichiers sont traités
              un par un par défaut.
            </p>
          </div>
        </div>
        <div className="system-tools">
          {health ? (
            Object.entries(health.tools).map(([name, available]) => (
              <div key={name}>
                <span className={cn("tool-status", available && "available")}>
                  {available ? <Check size={13} /> : <Circle size={12} />}
                </span>
                <strong>{name}</strong>
                <span>
                  {available
                    ? "Disponible"
                    : name === "ffsubsync"
                      ? "Sync. automatique indisponible"
                      : "Indisponible"}
                </span>
              </div>
            ))
          ) : (
            <p className="muted">État des outils indisponible.</p>
          )}
        </div>
        <div className="settings-note">
          <ShieldCheck size={16} />
          <div>
            <strong>Vos originaux ont le dernier mot.</strong>
            <p>
              Export externe à côté des MKV. Timings préservés par défaut. Aucun
              fichier existant n’est remplacé automatiquement.
            </p>
          </div>
        </div>
      </section>
      {editing && (
        <ProviderForm
          provider={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void client.invalidateQueries({ queryKey: ["providers"] });
            notify("Profil de traduction enregistré.");
          }}
        />
      )}
      <Modal
        open={!!deleting}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title="Supprimer ce profil ?"
        description={deleting?.name}
      >
        <p className="modal-body-copy">
          La configuration du provider et sa clé seront supprimées. Les
          sous-titres déjà exportés restent disponibles.
        </p>
        {remove.isError && <ErrorNotice error={message(remove.error)} />}
        <div className="modal-footer">
          <Button variant="outline" onClick={() => setDeleting(null)}>
            Conserver le profil
          </Button>
          <Button
            variant="destructive"
            onClick={() => deleting?.id && remove.mutate(deleting.id)}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Suppression…" : "Supprimer le profil"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function ProviderForm({
  provider,
  onClose,
  onSaved,
}: {
  provider: Provider;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Provider>({ ...provider, api_key: "" });
  const [advanced, setAdvanced] = useState(false);
  const [reveal, setReveal] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      api<Provider>("/providers", {
        ...form,
        api_key: form.api_key || undefined,
      }),
    onSuccess: onSaved,
  });
  const update = <K extends keyof Provider>(key: K, value: Provider[K]) =>
    setForm((old) => ({ ...old, [key]: value }));
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose();
      }}
      wide
      title={
        provider.id ? "Modifier le profil" : "Nouveau provider de traduction"
      }
      description="Choisissez un service et saisissez l’identifiant exact du modèle."
    >
      <form
        className="provider-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="form-grid">
          <label className="form-field">
            Nom du profil
            <input
              required
              autoFocus
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="Mon atelier · Animés"
              maxLength={100}
            />
          </label>
          <label className="form-field">
            Service
            <select
              value={form.kind}
              onChange={(e) => {
                const kind = e.target.value as ProviderKind;
                setForm((old) => ({
                  ...old,
                  kind,
                  base_url: kinds.find((k) => k.id === kind)!.base,
                }));
              }}
            >
              {kinds.map((kind) => (
                <option key={kind.id} value={kind.id}>
                  {kind.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="form-field">
          Identifiant du modèle
          <input
            required
            value={form.model}
            onChange={(e) => update("model", e.target.value)}
            placeholder="Identifiant du modèle fourni par le service"
            autoComplete="off"
            spellCheck={false}
          />
          <small>
            Saisissez le nom exact disponible sur votre compte ou votre serveur.
          </small>
        </label>
        <label className="form-field">
          URL de l’API
          <input
            type="url"
            value={form.base_url}
            onChange={(e) => update("base_url", e.target.value)}
            required={["ollama", "custom"].includes(form.kind)}
            placeholder={
              form.kind === "ollama"
                ? "http://votre-serveur:11434"
                : "https://votre-endpoint/v1"
            }
            spellCheck={false}
          />
          <small>
            {form.kind === "ollama"
              ? "Adresse joignable depuis le conteneur Sillage, y compris sur une autre machine du réseau."
              : "Modifiable pour les proxys et les endpoints compatibles."}
          </small>
        </label>
        <label className="form-field">
          Clé API
          {provider.has_key && (
            <span className="saved-key">
              <Check size={12} />
              Une clé est déjà enregistrée
            </span>
          )}
          <div className="secret-input">
            <input
              type={reveal ? "text" : "password"}
              value={form.api_key}
              onChange={(e) => update("api_key", e.target.value)}
              autoComplete="new-password"
              placeholder={
                provider.has_key
                  ? "Laisser vide pour conserver la clé actuelle"
                  : form.kind === "ollama"
                    ? "Facultative pour Ollama"
                    : "Clé du service"
              }
              spellCheck={false}
            />
            <button type="button" onClick={() => setReveal(!reveal)}>
              {reveal ? "Masquer" : "Afficher"}
            </button>
          </div>
          <small>
            Transmise au serveur à l’enregistrement. Jamais conservée dans le
            stockage local du navigateur.
          </small>
        </label>
        <div className="form-divider" />
        <div className="form-grid">
          <label className="form-field">
            Langue source
            <input
              value={form.source_language}
              onChange={(e) => update("source_language", e.target.value)}
              required
              placeholder="en"
              maxLength={30}
            />
          </label>
          <label className="form-field">
            Langue cible
            <input
              value={form.target_language}
              onChange={(e) => update("target_language", e.target.value)}
              required
              placeholder="fr"
              maxLength={30}
            />
          </label>
        </div>
        <label className="form-field">
          Glossaire et consignes de la série
          <span className="optional">Facultatif</span>
          <textarea
            rows={4}
            value={form.glossary}
            onChange={(e) => update("glossary", e.target.value)}
            placeholder={
              "Un terme ou une consigne par ligne.\nConserver les noms propres et les honorifiques."
            }
          />
          <small>
            Le glossaire est associé à ce profil. Dupliquez vos profils par
            série pour garder des termes cohérents.
          </small>
        </label>
        <button
          className="advanced-toggle"
          type="button"
          onClick={() => setAdvanced(!advanced)}
          aria-expanded={advanced}
        >
          <Settings2 size={15} />
          Réglages avancés
          <ChevronDown size={14} className={advanced ? "rotate" : ""} />
        </button>
        {advanced && (
          <div className="advanced-fields">
            <div className="form-grid three">
              <label className="form-field">
                Taille des lots
                <input
                  type="number"
                  required
                  min={1}
                  max={100}
                  value={form.batch_size}
                  onChange={(e) => update("batch_size", Number(e.target.value))}
                />
                <small>Segments par requête</small>
              </label>
              <label className="form-field">
                Concurrence
                <input
                  type="number"
                  required
                  min={1}
                  max={4}
                  value={form.concurrency}
                  onChange={(e) =>
                    update("concurrency", Number(e.target.value))
                  }
                />
                <small>Gardez 1 pour ménager le NAS</small>
              </label>
              <label className="form-field">
                Température
                <input
                  type="number"
                  step={0.1}
                  min={0}
                  max={2}
                  value={form.temperature ?? ""}
                  onChange={(e) =>
                    update(
                      "temperature",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                  placeholder="Défaut du modèle"
                />
                <small>Vide : réglage du service</small>
              </label>
            </div>
            <div className="form-grid">
              <label className="form-field">
                Timeout (secondes)
                <input
                  required
                  type="number"
                  min={5}
                  max={600}
                  value={form.timeout}
                  onChange={(e) => update("timeout", Number(e.target.value))}
                />
              </label>
              <label className="form-field">
                Nouvelles tentatives
                <input
                  required
                  type="number"
                  min={0}
                  max={5}
                  value={form.retries}
                  onChange={(e) => update("retries", Number(e.target.value))}
                />
              </label>
            </div>
          </div>
        )}
        {save.isError && <ErrorNotice error={message(save.error)} />}
        <div className="modal-footer form-footer">
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Annuler
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? (
              <Loader2 className="spin" size={15} />
            ) : (
              <Check size={15} />
            )}
            Enregistrer le profil
          </Button>
        </div>
      </form>
    </Modal>
  );
}
