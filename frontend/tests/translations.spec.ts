import { expect, test, type Page } from "@playwright/test";
import type { Job } from "../src/types";

test.skip(Boolean(process.env.E2E_BASE_URL), "Synthetic jobs use only the disposable fixture server.");

const jobs = (): Job[] => Array.from({ length: 26 }, (_, index) => ({
  id: `pagination-${index + 1}`,
  path: `/test-only/Episode ${String(index + 1).padStart(2, "0")}.mkv`,
  name: `Épisode ${String(index + 1).padStart(2, "0")}.mkv`,
  track_id: "stream:2", provider_id: "test-only", status: index === 0 ? "queued" : index % 2 ? "error" : "completed",
  progress: index === 0 ? 0 : index % 2 ? 20 : 100, done: index === 0 ? 0 : index % 2 ? 2 : 10, total: 10,
  error: index % 2 ? "Erreur de test" : null, warnings: [],
  output: index === 0 || index % 2 ? null : `/test-only/episode-${index + 1}.fr.srt`,
  created_at: "2026-10-26T00:00:00Z", sync_mode: "preserve", offset_ms: 0,
  timing_status: "Timings source préservés",
}));

async function readableFields(page: Page) {
  const fields = page.locator('input:not([type="checkbox"]):not([type="radio"]):visible, select:visible, textarea:visible');
  expect(await fields.count()).toBeGreaterThan(0);
  for (const field of await fields.all()) {
    expect(await field.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  }
  const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
  expect(viewport).not.toMatch(/user-scalable\s*=\s*(?:no|0)|maximum-scale\s*=/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

for (const mobile of [false, true]) {
  test(`translation pagination, filters and live updates ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1280, height: 640 });
    let records = jobs();
    let reads = 0;
    await page.route("**/api/jobs", (route) => {
      reads += 1;
      return route.fulfill({ json: records });
    });
    const nextPoll = async () => {
      const before = reads;
      await expect.poll(() => reads).toBeGreaterThan(before);
    };
    await page.goto("/#traductions");
    await page.getByRole("button", { name: "Liste", exact: true }).click();
    const top = page.getByRole("navigation", { name: "Pagination des traductions en haut", exact: true });
    const bottom = page.getByRole("navigation", { name: "Pagination des traductions en bas", exact: true });
    const cards = page.locator(".job-card");
    await expect(cards).toHaveCount(10);
    await expect(cards.first()).toContainText("Épisode 01.mkv");
    await expect(top).toContainText("1–10 sur 26 traductions");
    await expect(top.getByRole("button", { name: "Page précédente", exact: true })).toBeDisabled();
    await bottom.getByRole("button", { name: "Page suivante", exact: true }).click();
    await expect(cards.first()).toContainText("Épisode 11.mkv");
    await expect(top).toBeInViewport();
    await expect(top).toBeFocused();
    await expect(top).toContainText("Page 2 / 3");
    // A polling refresh must preserve the selected page rather than restart at page 1.
    records = records.map((job) => ({ ...job, progress: job.progress + 0.01 }));
    await nextPoll();
    await expect(top).toContainText("Page 2 / 3");
    await top.getByRole("button", { name: "Page suivante", exact: true }).click();
    await expect(cards).toHaveCount(6);
    await expect(top).toContainText("21–26 sur 26 traductions");
    await expect(top.getByRole("button", { name: "Page suivante", exact: true })).toBeDisabled();
    // When live results shrink, clamp to a valid page and keep it when they grow again.
    records = records.slice(0, 12);
    await nextPoll();
    await expect(top).toContainText("Page 2 / 2");
    await expect(cards).toHaveCount(2);
    records = jobs();
    await nextPoll();
    await expect(top).toContainText("Page 2 / 3");
    await page.getByRole("button", { name: /^Erreurs/ }).click();
    await expect(top).toContainText("Page 1 / 2");
    await expect(cards.first()).toContainText("Épisode 02.mkv");
    await top.getByRole("button", { name: "Page suivante", exact: true }).click();
    await expect(cards).toHaveCount(3);
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("Épisode 04");
    await expect(cards).toHaveCount(1);
    await expect(top).toContainText("Page 1 / 1");
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("absent");
    await expect(page.getByRole("heading", { name: "Aucune traduction ici", exact: true })).toBeVisible();
    await expect(top).toHaveCount(0);
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("");
    await page.getByRole("button", { name: /^Tout/ }).click();
    await page.getByLabel("Traductions par page", { exact: true }).selectOption("5");
    await expect(cards).toHaveCount(5);
    await expect(top).toContainText("Page 1 / 6");
    if (mobile) await readableFields(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `test-results/translations-pagination-${mobile ? "mobile" : "desktop"}.png`, fullPage: true });
    await page.getByLabel("Traductions par page", { exact: true }).selectOption("25");
    await expect(cards).toHaveCount(25);
    await expect(top).toContainText("Page 1 / 2");
  });
}

test.describe("touch form controls", () => {
  test.use({ isMobile: true, hasTouch: true });
  test("mobile fields stay readable across search, preview and advanced provider settings", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await readableFields(page);
    await page.getByRole("button", { name: "Les voyageurs", exact: true }).last().click();
    await page.getByTestId("scan-button").click();
    await expect(page.getByText("3 épisodes", { exact: true })).toBeVisible();
    await readableFields(page);
    await page.getByRole("button", { name: "Détails de Les voyageurs — S01E01.mkv", exact: true }).click();
    await readableFields(page);
    await page.getByRole("button", { name: "Fermer l’aperçu", exact: true }).click();
    await page.getByRole("button", { name: "Ouvrir la navigation", exact: true }).click();
    await page.getByRole("link", { name: "Paramètres", exact: true }).click();
    await page.getByRole("button", { name: "Ajouter un fournisseur", exact: true }).click();
    await page.getByRole("combobox", { name: "Fournisseur", exact: true }).selectOption("custom");
    await page.getByRole("button", { name: "Saisir un modèle manuellement", exact: true }).click();
    await page.getByRole("button", { name: "Réglages avancés", exact: true }).click();
    await readableFields(page);
    await page.getByLabel(/^Clé API/).focus();
    await page.screenshot({ path: "test-results/mobile-fields.png", fullPage: false });
    await page.setViewportSize({ width: 844, height: 390 });
    await readableFields(page);
    const save = page.getByRole("button", { name: "Enregistrer le profil", exact: true });
    await save.scrollIntoViewIfNeeded();
    await expect(save).toBeInViewport();
    await page.screenshot({ path: "test-results/mobile-fields-landscape.png", fullPage: false });
  });
});

for (const mobile of [false, true]) {
  test(`pause one episode and scoped queue across pages ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1280, height: 800 });
    let records = jobs().slice(0, 14).map((job, index): Job => ({ ...job, status: "queued", error: null, output: null,
      path: `/test-only/${index < 12 ? "Group A" : "Group B"}/${job.name}`, done: 0, progress: 0 }));
    const groups: string[][] = [];
    const resumed: string[] = [];
    await page.route("**/api/jobs", (route) => route.fulfill({ json: records }));
    await page.route("**/api/jobs/*/pause", (route) => {
      const id = route.request().url().split("/").at(-2)!;
      records = records.map((job) => job.id === id ? { ...job, status: "pausing" } : job);
      return route.fulfill({ json: records.find((job) => job.id === id) });
    });
    await page.route("**/api/jobs/pause", (route) => {
      const ids: string[] = route.request().postDataJSON().ids;
      groups.push(ids);
      records = records.map((job) => ids.includes(job.id) ? { ...job, status: "paused" } : job);
      return route.fulfill({ json: records.filter((job) => ids.includes(job.id)) });
    });
    await page.route("**/api/jobs/*/resume", (route) => {
      const id = route.request().url().split("/").at(-2)!;
      resumed.push(id);
      records = records.map((job) => job.id === id ? { ...job, status: "queued" } : job);
      return route.fulfill({ json: records.find((job) => job.id === id) });
    });
    await page.goto("/#traductions");
    await page.getByRole("button", { name: "Liste", exact: true }).click();
    await page.getByLabel("Traductions par page", { exact: true }).selectOption("5");
    await page.getByLabel("Rechercher une traduction", { exact: true }).fill("Group A");
    const first = page.locator('.job-card').first();
    await first.getByRole("button", { name: "Pause", exact: true }).click();
    await expect(first.getByText("Pause demandée", { exact: true })).toBeVisible();
    await expect(first.getByRole("button", { name: "Reprendre", exact: true })).toHaveCount(0);
    records = records.map((job) => job.status === 'pausing' ? { ...job, status: 'paused' } : job);
    await expect(first.getByRole("button", { name: "Reprendre", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Mettre en pause (11)", exact: true }).click();
    await expect.poll(() => groups.length).toBe(1);
    expect(groups[0]).toHaveLength(11); // Includes episodes on pages two and three.
    expect(records.filter((job) => job.path.includes('Group B')).every((job) => job.status === 'queued')).toBe(true);
    await page.getByRole("button", { name: "Reprendre les pauses (12)", exact: true }).click();
    await expect.poll(() => resumed.length).toBe(12);
    expect(new Set(resumed).size).toBe(12);
    await expect(first.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
    if (mobile) await readableFields(page);
    await page.screenshot({ path: `test-results/translations-pause-${mobile ? "mobile" : "desktop"}.png`, fullPage: true });
  });
}
