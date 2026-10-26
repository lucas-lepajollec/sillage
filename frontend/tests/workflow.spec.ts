import { expect, test } from "@playwright/test";

// All source media and the deterministic HTTP provider come from tests/serve_e2e.py.
// This exercises the real FastAPI/worker/SQLite/FFmpeg/provider/export path.
test("real library → track preview → provider → selected episodes → export", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("heading", { name: "Explorer", exact: true }).waitFor();
  await page
    .getByRole("button", { name: "Les voyageurs", exact: true })
    .last()
    .click();
  await page.getByTestId("scan-button").click();
  await expect(page.getByText("3 épisodes", { exact: true })).toBeVisible();
  await page
    .getByRole("button", {
      name: "Détails de Les voyageurs — S01E01.mkv",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Hello");
  await expect(
    page.getByRole("dialog").locator(".cue-source").first(),
  ).not.toContainText("\\i1");
  await page.getByRole("dialog").getByLabel("Balises", { exact: true }).check();
  await expect(
    page.getByRole("dialog").locator(".cue-source").first(),
  ).toContainText("\\i1");
  await page.getByRole("button", { name: "Fermer l’aperçu" }).click();
  await page
    .getByRole("checkbox", {
      name: "Sélectionner Les voyageurs — S01E01.mkv",
      exact: true,
    })
    .check();
  await page
    .getByRole("checkbox", {
      name: "Sélectionner Les voyageurs — S01E02.mkv",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Configurer un provider", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Ajouter un fournisseur", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^Nom du profil/).fill("Provider de test HTTP");
  await dialog
    .getByRole("combobox", { name: "Fournisseur", exact: true })
    .selectOption("custom");
  await dialog.getByLabel(/^URL du serveur/).fill("http://127.0.0.1:5777/v1");
  await dialog
    .getByRole("button", { name: "Charger les modèles", exact: true })
    .click();
  await dialog
    .getByRole("combobox", { name: "Modèle", exact: true })
    .selectOption("sillage-test-only");
  await dialog
    .getByRole("button", { name: "Enregistrer le profil", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Tester la connexion", exact: true })
    .click();
  await expect(page.locator(".provider-test-result")).toContainText(
    "Connexion et réponse structurée du modèle validées.",
  );
  await page.getByRole("link", { name: "Explorer", exact: true }).click();
  await expect(
    page.getByRole("checkbox", {
      name: "Sélectionner Les voyageurs — S01E01.mkv",
      exact: true,
    }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", {
      name: "Sélectionner Les voyageurs — S01E02.mkv",
      exact: true,
    }),
  ).toBeChecked();
  await page.screenshot({
    path: "test-results/explorer-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Traduire", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Traductions", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".job-card.job-review")).toHaveCount(2, {
    timeout: 30_000,
  });
  await expect(page.locator(".job-card")).toHaveCount(2);
  await page.locator(".job-warnings summary").first().click();
  await expect(page.locator(".job-warnings").first()).toContainText("désactivation du raisonnement ne peut pas être confirmée");
  await expect(page.getByText("Lots ≤ 4 répliques", { exact: false }).first()).toBeVisible();
  await page
    .locator(".job-card")
    .first()
    .getByRole("button", { name: "Aperçu", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").locator(".cue-translated").first(),
  ).toContainText("Bonjour");
  await expect(page.getByRole("dialog")).toContainText(
    "Timings source préservés",
  );
  await page.screenshot({
    path: "test-results/translation-preview-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Fermer l’aperçu" }).click();
  const downloading = page.waitForEvent("download");
  await page
    .locator(".job-card")
    .first()
    .getByRole("button", { name: "Télécharger", exact: true })
    .click();
  expect((await downloading).suggestedFilename()).toMatch(/\.fr\.(ass|srt)$/);
  await page.getByRole("button", { name: "Activer le thème clair" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({
    path: "test-results/translations-light.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});

test("mobile layout, navigation, filters, empty and source drawer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("heading", { name: "Explorer", exact: true }).waitFor();
  await page
    .getByRole("button", { name: "Les voyageurs", exact: true })
    .last()
    .click();
  await page.getByTestId("scan-button").click();
  await expect(page.getByText("3 épisodes", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Filtres", exact: true }).click();
  await page.getByLabel("Sans français uniquement").check();
  await expect(page.locator(".episode-status.episode-french")).toHaveCount(0);
  await page
    .getByLabel("Rechercher un fichier ou un dossier")
    .fill("introuvable");
  await expect(
    page.getByRole("heading", { name: "Aucun épisode ne correspond" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Effacer les filtres", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Détails de Les voyageurs — S01E03.mkv",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("dialog").locator(".cue-source").first(),
  ).toContainText("Hello");
  await page.screenshot({
    path: "test-results/preview-mobile.png",
    fullPage: false,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Fermer l’aperçu" }).click();
  await page.getByRole("button", { name: "Ouvrir la navigation" }).click();
  await page.getByRole("link", { name: "Paramètres", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Paramètres", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/settings-mobile.png",
    fullPage: false,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
