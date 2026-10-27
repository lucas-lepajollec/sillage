import { expect, test } from "@playwright/test";
import { matchSourceTrack } from "../src/tracks";
import type { Episode, Track } from "../src/types";

const reference: Track = { id: "embedded:3", index: 3, title: "Dialogue", language: "eng", format: "ass", default: true, forced: false, sdh: false, external: false, supported: true };
const episode = (tracks: Track[]) => ({ tracks }) as Episode;

test("group matching uses track identity rather than stream order and refuses ambiguity", () => {
  const reordered = { ...reference, id: "embedded:7", index: 7, language: "en", title: "  DIALOGUE  ", default: false };
  const signs = { ...reference, id: "embedded:2", title: "Signs & Songs", forced: true };
  expect(matchSourceTrack(episode([signs, reordered]), reference).track?.id).toBe("embedded:7");
  expect(matchSourceTrack(episode([signs]), reference).track).toBeUndefined();
  expect(matchSourceTrack(episode([reference, reordered]), reference).reason).toContain("Plusieurs");
  for (const changed of [{ sdh: true }, { forced: true }, { format: "srt" }, { supported: false }, { external: true }, { language: "fr" }]) {
    expect(matchSourceTrack(episode([{ ...reference, ...changed }]), reference).track).toBeUndefined();
  }
  const external = { ...reference, external: true, title: "Episode1.en.ass" };
  expect(matchSourceTrack(episode([{ ...external, title: "Episode2.en.ass" }]), external).track).toBeDefined();
  expect(matchSourceTrack(episode([external, { ...external, id: "external:other" }]), external).track).toBeUndefined();
});

for (const mobile of [false, true]) {
  test(`source selection, preview and group scopes ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    let paidCalls = 0;
    page.on("request", (request) => {
      if (/\/api\/(jobs$|providers\/[^/]+\/test)/.test(request.url()) && request.method() === "POST") paidCalls++;
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Pistes multiples", exact: true }).last().click();
    await page.getByTestId("scan-button").click();
    await expect(page.getByText("5 épisodes", { exact: true })).toBeVisible();
    const source = (number: number) => page.getByLabel(`Piste source de Pistes — E0${number}.mkv`, { exact: true });
    await expect(source(1).locator("option:checked")).toContainText("Dialogue");
    await expect(source(2).locator("option:checked")).toContainText("Dialogue");
    await page.getByRole("button", { name: "Détails de Pistes — E01.mkv", exact: true }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer.getByLabel("Informations de la piste source")).toContainText("Dialogue");
    await expect(drawer.getByLabel("Comptage des événements")).toContainText("2 à traduire par l’IA");
    await drawer.getByLabel("Piste à prévisualiser", { exact: true }).selectOption("embedded:2");
    await expect(drawer.locator(".cue-source").first()).toContainText("Sign only");
    await expect(drawer.getByLabel("Comptage des événements")).toContainText("1 à traduire par l’IA");
    await expect(drawer.getByLabel("Informations de la piste source")).toContainText("peut ne pas contenir les dialogues complets");
    await drawer.getByRole("button", { name: "Revenir au choix automatique" }).click();
    await expect(drawer.locator(".cue-source").first()).toContainText("Hello");
    await drawer.getByRole("button", { name: "Appliquer à d’autres épisodes" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Appliquer à", { exact: true })).toHaveValue("folder");
    await expect(dialog.getByRole("status")).toContainText("2 / 4");
    await expect(dialog.getByLabel("Vérification des correspondances")).toContainText("Plusieurs pistes correspondent");
    await expect(dialog.getByRole("button", { name: "Appliquer à 2 épisode(s)", exact: true })).toBeInViewport();
    await page.screenshot({ path: `test-results/source-track-matching-${mobile ? "mobile" : "desktop"}.png`, fullPage: true, animations: "disabled" });
    await dialog.getByRole("button", { name: "Appliquer à 2 épisode(s)", exact: true }).click();
    await expect(source(1).locator("option:checked")).toContainText("Dialogue");
    await expect(source(2).locator("option:checked")).toContainText("Dialogue");
    // Only the two checked episodes change, including one in another folder.
    for (const number of [1, 5]) await page.getByRole("checkbox", { name: `Sélectionner Pistes — E0${number}.mkv`, exact: true }).check();
    await page.getByRole("button", { name: "Choisir les pistes", exact: true }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Appliquer à", { exact: true })).toHaveValue("selected");
    await dialog.getByLabel("Piste de référence", { exact: true }).selectOption("embedded:2");
    await expect(dialog.getByRole("status")).toContainText("2 / 2");
    await dialog.getByRole("button", { name: "Appliquer à 2 épisode(s)", exact: true }).click();
    await expect(source(1)).toHaveValue("embedded:2");
    await expect(source(5)).toHaveValue("embedded:2");
    await expect(source(2)).toHaveValue("embedded:2"); // Dialogue is stream 2 in this file.
    await page.getByRole("button", { name: "Fermer la notification", exact: true }).click();
    // Whole scan scope is explicit, even when a search hides most rows.
    await page.getByLabel("Rechercher un fichier ou un dossier").fill("E01");
    await page.getByRole("button", { name: "Choisir les pistes", exact: true }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Appliquer à", { exact: true }).selectOption("all");
    await dialog.getByLabel("Choix de piste", { exact: true }).selectOption("auto");
    await expect(dialog.getByRole("status")).toContainText("5 / 5");
    if (mobile) {
      const size = await dialog.getByLabel("Appliquer à", { exact: true }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(size).toBeGreaterThanOrEqual(16);
    }
    await page.screenshot({ path: `test-results/source-tracks-${mobile ? "mobile" : "desktop"}.png`, fullPage: true, animations: "disabled" });
    await dialog.getByRole("button", { name: "Appliquer à 5 épisode(s)", exact: true }).click();
    await page.getByLabel("Rechercher un fichier ou un dossier").fill("");
    await expect(source(1).locator("option:checked")).toContainText("Dialogue");
    await expect(source(5).locator("option:checked")).toContainText("Dialogue");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(paidCalls).toBe(0);
  });
}
