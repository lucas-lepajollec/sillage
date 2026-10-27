import { expect, test } from "@playwright/test";
import type { Job } from "../src/types";

test.skip(Boolean(process.env.E2E_BASE_URL), "History fixtures use only the disposable test server.");

function history(): Job[] {
  const jobs: Job[] = Array.from({ length: 24 }, (_, index) => ({
    id: String(index + 1).padStart(32, "0"),
    name: "Épisode 01.mkv", path: `/media/Serie ${String(index + 1).padStart(2, "0")}/Saison 1/Épisode 01.mkv`,
    status: index === 0 ? "queued" : index % 2 ? "error" : "completed",
    track_id: "embedded:2", provider_id: "test-only", progress: index % 2 ? 20 : 100,
    done: 2, total: 10, error: null, warnings: [], output: null,
    created_at: "2026-10-27T00:00:00Z", sync_mode: "preserve", offset_ms: 0, timing_status: "source",
  }));
  return [...jobs, { ...jobs[0], id: "9".repeat(32), status: "cancelled" }];
}

for (const mobile of [false, true]) {
  test(`folders, scoped cleanup and persisted list view ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
    let records = history();
    const removed: string[][] = [];
    const resumed: string[] = [];
    await page.route("**/api/jobs", (route) => route.fulfill({ json: records }));
    await page.route("**/api/jobs/delete", async (route) => {
      const { ids } = route.request().postDataJSON() as { ids: string[] };
      removed.push(ids);
      records = records.filter((job) => !ids.includes(job.id));
      await route.fulfill({ json: { deleted: ids, warnings: [] } });
    });
    await page.route("**/api/jobs/*/resume", async (route) => {
      const id = route.request().url().split("/").at(-2)!;
      resumed.push(id);
      records = records.map((job) => job.id === id ? { ...job, status: "queued" } : job);
      await route.fulfill({ json: records.find((job) => job.id === id) });
    });
    await page.goto("/#traductions");
    const top = page.getByRole("navigation", { name: "Pagination des traductions en haut", exact: true });
    await expect(page.locator(".job-folder-card")).toHaveCount(10);
    await expect(top).toContainText("1–10 sur 24 dossiers");
    if (mobile) expect(await page.getByLabel("Dossiers par page", { exact: true }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
    await top.getByRole("button", { name: "Page suivante", exact: true }).click();
    await expect(top).toContainText("Page 2 / 3");
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("Serie 01");
    await expect(page.locator(".job-folder-card")).toHaveCount(1);
    await expect(page.locator(".job-folder-card")).toContainText("2 traductions · 1 en cours");
    await page.locator(".job-folder-card").click();
    await expect(page.locator(".job-card")).toHaveCount(2);
    await expect(page.locator(".job-queued").getByRole("button", { name: /^Supprimer de l’historique/ })).toBeDisabled();
    await page.locator(".job-cancelled").getByRole("button", { name: /^Supprimer de l’historique/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Conserver", exact: true }).click();
    expect(removed).toEqual([]);
    await page.getByRole("button", { name: "Nettoyer l’historique (1)", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText("Les MKV, pistes source");
    await page.getByRole("button", { name: "Supprimer définitivement ces entrées", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(1);
    expect(removed).toEqual([["9".repeat(32)]]);
    await page.getByRole("button", { name: "Tous les dossiers", exact: true }).click();
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("Serie 02");
    await page.locator(".job-folder-card").click();
    await page.getByRole("button", { name: "Reprendre les erreurs (1)", exact: true }).click();
    await expect.poll(() => resumed).toEqual([String(2).padStart(32, "0")]);
    await page.getByRole("button", { name: "Tous les dossiers", exact: true }).click();
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("");
    await page.getByRole("button", { name: "Fermer la notification", exact: true }).click();
    await page.screenshot({ path: `test-results/history-folders-${mobile ? "mobile" : "desktop"}.png`, fullPage: true, animations: "disabled" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Liste", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(10);
    await page.reload();
    await expect(page.getByRole("button", { name: "Liste", exact: true })).toHaveAttribute("aria-pressed", "true");
  });
}

test("mobile reanalysis prepares one real source without starting a generation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const root = (await (await page.request.get("/api/browse")).json()).path;
  const scan = await (await page.request.post("/api/scan", { data: { path: root, recursive: true } })).json();
  const episode = scan.episodes.find((e: { name: string }) => e.name === "Pistes — E01.mkv");
  const job: Job = { ...history()[1], path: episode.path, name: episode.name, track_id: "embedded:99" };
  let generations = 0;
  await page.route("**/api/jobs", (route) => {
    if (route.request().method() === "POST") generations++;
    return route.fulfill({ json: [job] });
  });
  await page.route("**/api/jobs/*/reanalyze", (route) => route.fulfill({ json: episode }));
  await page.route("**/api/scan", (route) => route.fulfill({ status: 400, json: { detail: "Erreur d’analyse de test" } }));
  await page.goto("/");
  await page.getByTestId("scan-button").click();
  await expect(page.locator(".explorer-page")).toContainText("Erreur d’analyse de test");
  await page.getByRole("button", { name: "Ouvrir la navigation", exact: true }).click();
  await page.getByRole("link", { name: "Traductions", exact: true }).click();
  await page.locator(".job-folder-card").click();
  await page.getByRole("button", { name: `Réanalyser ${job.name}`, exact: true }).click();
  await expect(page.getByRole("dialog").getByLabel("Informations de la piste source")).toContainText("Dialogue");
  await expect(page.getByRole("dialog").locator(".cue-source").first()).toContainText("Hello");
  await expect(page.locator(".toast")).toContainText("L’ancienne piste n’est plus disponible");
  await page.getByRole("button", { name: "Fermer l’aperçu", exact: true }).click();
  await page.getByRole("button", { name: "Fermer la notification", exact: true }).click();
  await expect(page.locator(".reanalysis-notice")).toContainText("L’ancien traitement et ses checkpoints sont conservés");
  await expect(page.getByText("1 épisode", { exact: true })).toBeVisible();
  await expect(page.getByLabel(`Sélectionner ${job.name}`, { exact: true })).toBeChecked();
  await expect(page.locator(".explorer-page")).not.toContainText("Erreur d’analyse de test");
  await page.getByRole("button", { name: "Dossier parent", exact: true }).click();
  await expect(page.locator(".reanalysis-notice")).toHaveCount(0);
  expect(generations).toBe(0);
});

for (const mobile of [false, true]) {
  test(`adapt one or scoped stopped translations without explorer ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
    const records = history();
    const profiles = [{ id: "test-only", name: "Cloud", model: "model-current", kind: "custom" }];
    const requests: { ids: string[]; provider_id: string; restart: boolean }[] = [];
    let scans = 0;
    await page.route("**/api/providers", (route) => route.fulfill({ json: profiles }));
    await page.route("**/api/jobs", (route) => route.fulfill({ json: records }));
    await page.route("**/api/scan", (route) => { scans++; return route.fulfill({ json: { episodes: [], errors: [] } }); });
    await page.route("**/api/jobs/reconfigure", async (route) => {
      requests.push(route.request().postDataJSON());
      if (requests.length === 1) return route.fulfill({ status: 400, json: { detail: "Annulez le traitement actif avant de l’adapter." } });
      return route.fulfill({ json: records.filter((job) => requests.at(-1)!.ids.includes(job.id)) });
    });
    await page.goto("/#traductions");
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("Serie 02");
    await page.locator(".job-folder-card").click();
    await page.getByRole("button", { name: "Adapter les paramètres (1)", exact: true }).click();
    const modal = page.getByRole("dialog", { name: "Adapter les paramètres", exact: true });
    await expect(modal.getByLabel("Conserver les segments validés", { exact: true })).toBeChecked();
    await expect(modal.getByLabel("Profil pour la reprise", { exact: true })).toHaveValue("test-only");
    await expect(modal).toContainText("même piste source, sans nouvelle analyse");
    await modal.getByRole("button", { name: "Confirmer et reprendre", exact: true }).click();
    await expect(modal).toContainText("Annulez le traitement actif");
    expect(requests[0]).toEqual({ ids: [String(2).padStart(32, "0")], provider_id: "test-only", restart: false });
    if (mobile) expect(await modal.getByLabel("Profil pour la reprise", { exact: true }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
    await page.screenshot({ path: `test-results/recovery-settings-${mobile ? "mobile" : "desktop"}.png`, fullPage: true, animations: "disabled" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await modal.getByLabel("Recommencer la traduction", { exact: true }).check();
    await expect(modal).toContainText("seront effacés et retraduits");
    await modal.getByRole("button", { name: "Confirmer et recommencer", exact: true }).click();
    await expect(modal).not.toBeVisible();
    expect(requests[1].restart).toBe(true);
    await page.getByRole("button", { name: "Adapter les paramètres de Épisode 01.mkv", exact: true }).click();
    await expect(modal.getByLabel("Conserver les segments validés", { exact: true })).toBeChecked();
    await modal.getByLabel("Fermer", { exact: true }).click();
    expect(scans).toBe(0);
  });
}
