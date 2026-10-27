import { useEffect, useRef, useState } from "react";
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
import type { Health, ModelCatalog, Provider, ProviderKind } from "../types";
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
  { id: "deepseek", label: "DeepSeek", base: "https://api.deepseek.com/v1" },
  {
    id: "openrouter",
    label: "OpenRouter",
    base: "https://openrouter.ai/api/v1",
  },
  { id: "groq", label: "Groq", base: "https://api.groq.com/openai/v1" },
  { id: "mistral", label: "Mistral", base: "https://api.mistral.ai/v1" },
  { id: "xai", label: "xAI / Grok", base: "https://api.x.ai/v1" },
  { id: "ollama", label: "Ollama", base: "" },
  { id: "lmstudio", label: "LM Studio", base: "" },
  { id: "vllm", label: "vLLM", base: "" },
  { id: "llamacpp", label: "llama.cpp", base: "" },
  { id: "custom", label: "Serveur compatible OpenAI", base: "" },
];
const localKinds = new Set<ProviderKind>(["ollama", "lmstudio", "vllm", "llamacpp", "custom"]);
const emptyProvider = (): Provider => ({
  name: "",
  kind: "openai",
  base_url: kinds[0].base,
  model: "",
  temperature: null,
  batch_size: 20,
  concurrency: 1,
  timeout: 120,
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
          Ajouter un fournisseur
        </Button>
      </div>
      <section className="settings-section">
        <div className="settings-section-heading">
          <div>
            <h2>
              <Cpu size={18} />
              Fournisseurs de traduction
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
        {loading && <Spinner>Chargement des fournisseurs…</Spinner>}
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
                  Connecter mon premier fournisseur
                  <ArrowRight size={14} />
                </Button>
              }
            >
              Choisissez un fournisseur, ajoutez votre clé et sélectionnez un
              modèle. Vous pouvez enregistrer plusieurs profils, cloud ou
              locaux.
            </Empty>
            <div className="provider-types">
              {kinds.map((kind) => <span key={kind.id}>{kind.label}</span>)}
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
                    localKinds.has(provider.kind) && "local",
                  )}
                >
                  {localKinds.has(provider.kind) ? (
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
                    : localKinds.has(provider.kind)
                      ? "Serveur local"
                      : "Sans clé"}
                </span>
                <span>Lots adaptatifs · plafond {provider.batch_size}</span>
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
          La configuration du fournisseur et sa clé seront supprimées. Les
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
  const [manual, setManual] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [search, setSearch] = useState("");
  const requestId = useRef(0);
  const loadingRef = useRef(false);
  const local = localKinds.has(form.kind);
  const selectedWarning = catalog?.models.find((model) => model.id === form.model)?.warning;
  const sameService =
    form.kind === provider.kind && form.base_url === provider.base_url;
  const savedKey = sameService && provider.has_key;
  const readyToLoad = local
    ? Boolean(form.base_url.trim())
    : Boolean(form.api_key?.trim() || savedKey);
  const kind = kinds.find((item) => item.id === form.kind)!;
  const filtered = (catalog?.models || []).filter((model) =>
    `${model.id} ${model.name}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  const currentMissing = Boolean(
    form.model && !filtered.some((model) => model.id === form.model),
  );
  const save = useMutation({
    mutationFn: () =>
      api<Provider>("/providers", {
        ...form,
        name: form.name.trim() || `${kind.label} · ${form.model}`.slice(0, 100),
        api_key: form.api_key || undefined,
      }),
    onSuccess: onSaved,
  });
  useEffect(
    () => () => {
      requestId.current += 1;
    },
    [],
  );
  const invalidateCatalog = () => {
    requestId.current += 1;
    loadingRef.current = false;
    setCatalog(null);
    setModelError(null);
    setLoadingModels(false);
    setSearch("");
  };
  const update = <K extends keyof Provider>(key: K, value: Provider[K]) => {
    if (key === "api_key" || key === "base_url") invalidateCatalog();
    setForm((old) => ({ ...old, [key]: value }));
  };
  const loadModels = async () => {
    if (!readyToLoad || loadingRef.current) return;
    const id = ++requestId.current;
    loadingRef.current = true;
    setLoadingModels(true);
    setModelError(null);
    try {
      const result = await api<ModelCatalog>("/providers/models", {
        id: sameService ? provider.id : undefined,
        kind: form.kind,
        base_url: form.base_url,
        api_key: form.api_key || "",
      });
      if (id !== requestId.current) return;
      setCatalog(result);
      if (result.models.length === 1 && !form.model) {
        setForm((old) =>
          old.model ? old : { ...old, model: result.models[0].id },
        );
      }
    } catch (error) {
      if (id === requestId.current) setModelError(message(error));
    } finally {
      if (id === requestId.current) {
        loadingRef.current = false;
        setLoadingModels(false);
      }
    }
  };
  const endpoint = (
    <label className="form-field">
      {local ? "URL du serveur" : "URL de l’API"}
      <input
        type="url"
        value={form.base_url}
        onChange={(e) => update("base_url", e.target.value)}
        required={local}
        placeholder={
          form.kind === "ollama"
            ? "http://votre-serveur:11434"
            : form.kind === "lmstudio"
              ? "http://votre-serveur:1234/api/v1"
              : form.kind === "llamacpp"
                ? "http://votre-serveur:8080/v1"
                : "http://votre-serveur:8000/v1"
        }
        spellCheck={false}
      />
      <small>
        {form.kind === "ollama"
          ? "Adresse de votre serveur Ollama, joignable depuis Sillage."
          : form.kind === "lmstudio"
            ? "API native LM Studio : ajoutez /api/v1 à l’adresse du serveur."
            : ["custom", "vllm", "llamacpp"].includes(form.kind)
              ? "API compatible OpenAI : ajoutez /v1 à l’adresse du serveur."
            : "Adresse du service, à modifier uniquement si vous utilisez un proxy."}
      </small>
    </label>
  );
  return (
    <Modal
      open
      wide
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose();
      }}
      title={provider.id ? "Modifier le profil" : "Connecter un fournisseur"}
      description="Choisissez un service, puis un modèle. Vous pouvez ajouter autant de profils que nécessaire."
    >
      <form
        className="provider-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (form.model.trim() && !loadingModels && !save.isPending)
            save.mutate();
        }}
      >
        <label className="form-field">
          Fournisseur
          <select
            autoFocus
            value={form.kind}
            onChange={(e) => {
              const nextKind = e.target.value as ProviderKind;
              invalidateCatalog();
              setManual(false);
              setReveal(false);
              setForm((old) => ({
                ...old,
                kind: nextKind,
                model: "",
                api_key: "",
                base_url: kinds.find((item) => item.id === nextKind)!.base,
              }));
            }}
          >
            {kinds.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {local && endpoint}
        <label className="form-field">
          Clé API{local && <span className="optional">Facultative</span>}
          {savedKey && (
            <span className="saved-key">
              <Check size={12} />
              Clé enregistrée
            </span>
          )}
          <div className="secret-input">
            <input
              type={reveal ? "text" : "password"}
              value={form.api_key}
              onChange={(e) => update("api_key", e.target.value)}
              onBlur={() => {
                if (form.api_key?.trim() && !catalog) void loadModels();
              }}
              required={!local && !savedKey}
              autoComplete="new-password"
              placeholder={
                savedKey
                  ? "Laisser vide pour conserver la clé"
                  : local
                    ? "Si votre serveur demande une clé"
                    : "Votre clé API"
              }
              spellCheck={false}
            />
            <button type="button" onClick={() => setReveal(!reveal)}>
              {reveal ? "Masquer" : "Afficher"}
            </button>
          </div>
          <small>La clé sera chiffrée sur le serveur à l’enregistrement.</small>
        </label>
        <div className="form-field model-discovery">
          <div className="model-discovery-heading">
            <label htmlFor="provider-model">Modèle</label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void loadModels()}
              disabled={loadingModels || !readyToLoad}
            >
              {loadingModels ? (
                <Loader2 size={14} className="spin" />
              ) : (
                <Cpu size={14} />
              )}
              {loadingModels
                ? "Chargement…"
                : catalog
                  ? "Actualiser les modèles"
                  : "Charger les modèles"}
            </Button>
          </div>
          {manual ? (
            <input
              id="provider-model"
              aria-label="Identifiant du modèle"
              required
              value={form.model}
              onChange={(e) => update("model", e.target.value)}
              placeholder="Identifiant exact fourni par le service"
              autoComplete="off"
              spellCheck={false}
            />
          ) : (
            <>
              {(catalog?.models.length || 0) > 8 && (
                <input
                  type="search"
                  aria-label="Rechercher un modèle"
                  placeholder="Rechercher un modèle…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              )}
              <select
                id="provider-model"
                required
                value={form.model}
                onChange={(e) => update("model", e.target.value)}
                disabled={loadingModels || (!catalog && !form.model)}
              >
                <option value="">
                  {catalog
                    ? "Choisir un modèle"
                    : "Chargez les modèles pour choisir"}
                </option>
                {currentMissing && (
                  <option value={form.model}>
                    {form.model} · sélection actuelle
                  </option>
                )}
                {filtered.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name === model.id
                      ? model.id
                      : `${model.name} · ${model.id}`}
                    {model.reasoning === "mandatory" ? " · raisonnement obligatoire" : ""}
                  </option>
                ))}
              </select>
            </>
          )}
          {loadingModels && (
            <small role="status">
              Lecture des modèles disponibles sur le service…
            </small>
          )}
          {catalog && !loadingModels && (
            <small role="status">
              {catalog.models.length === 0
                ? "Le service n’a renvoyé aucun modèle de texte. La saisie manuelle reste disponible."
                : `${catalog.models.length} modèle${catalog.models.length > 1 ? "s" : ""} reçu${catalog.models.length > 1 ? "s" : ""} du service.`}
              {catalog.truncated &&
                " Liste partielle : un autre identifiant peut être saisi manuellement."}
            </small>
          )}
          {catalog && search && !filtered.length && (
            <small>Aucun modèle ne correspond à cette recherche.</small>
          )}
          {modelError && <ErrorNotice error={modelError} />}
          <button
            type="button"
            className="model-manual-toggle"
            onClick={() => setManual(!manual)}
          >
            {manual ? "Choisir dans la liste" : "Saisir un modèle manuellement"}
          </button>
        </div>
        <small className="provider-defaults" role={selectedWarning ? "status" : undefined}>
          {selectedWarning || "Le raisonnement est désactivé quand le modèle le permet. S’il est obligatoire, la traduction continue avec un avertissement sur le délai et les tokens."}
        </small>
        <label className="form-field">
          Nom du profil<span className="optional">Facultatif</span>
          <input
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            placeholder={
              form.model
                ? `${kind.label} · ${form.model}`
                : "Nom automatique à partir du modèle"
            }
            maxLength={100}
          />
        </label>
        <button
          className="advanced-toggle"
          type="button"
          onClick={() => setAdvanced(!advanced)}
          aria-expanded={advanced}
          aria-controls="provider-advanced"
        >
          <Settings2 size={15} />
          Réglages avancés
          <ChevronDown size={14} className={advanced ? "rotate" : ""} />
        </button>
        {!advanced && (
          <small className="provider-defaults">
            {form.source_language.toUpperCase()} →{" "}
            {form.target_language.toUpperCase()} · Langues, glossaire et limites
            personnalisables
          </small>
        )}
        {advanced && (
          <div className="advanced-fields" id="provider-advanced">
            {!local && endpoint}
            <div className="form-grid">
              <label className="form-field">
                Langue source
                <input
                  value={form.source_language}
                  onChange={(e) => update("source_language", e.target.value)}
                  required
                  maxLength={30}
                />
              </label>
              <label className="form-field">
                Langue cible
                <input
                  value={form.target_language}
                  onChange={(e) => update("target_language", e.target.value)}
                  required
                  maxLength={30}
                />
              </label>
            </div>
            <label className="form-field">
              Glossaire et consignes de la série
              <textarea
                rows={3}
                value={form.glossary}
                onChange={(e) => update("glossary", e.target.value)}
                placeholder="Conserver les noms propres. Un terme ou une consigne par ligne."
              />
              <small>
                Ces termes s’appliquent aux traductions de ce profil.
              </small>
            </label>
            <div className="form-grid three">
              <label className="form-field">
                Taille maximale des lots
                <input
                  type="number"
                  required
                  min={1}
                  max={100}
                  value={form.batch_size}
                  onChange={(e) => update("batch_size", Number(e.target.value))}
                />
                <small>
                  Plafond : les lots démarrent plus petits et diminuent
                  temporairement si le modèle échoue, puis remontent après plusieurs réussites.
                </small>
              </label>
              <label className="form-field">
                Concurrence
                <input
                  type="number"
                  required
                  min={1}
                  max={8}
                  value={form.concurrency}
                  onChange={(e) =>
                    update("concurrency", Number(e.target.value))
                  }
                />
                <small>1 à 8 lots simultanés. Ces limites s’appliquent aux prochaines requêtes des traitements existants, sans perdre leur progression.</small>
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
                  min={1}
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
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={save.isPending}
          >
            Annuler
          </Button>
          <Button
            type="submit"
            disabled={save.isPending || !form.model.trim() || loadingModels}
          >
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
