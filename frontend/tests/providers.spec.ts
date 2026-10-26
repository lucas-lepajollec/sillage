import { expect, test } from "@playwright/test";

test.skip(
  Boolean(process.env.E2E_BASE_URL),
  "Provider setup uses only the disposable fixture server.",
);

// Browser-facing cloud responses are isolated fixtures; no real cloud is called.
// Native HTTP/catalogue contracts and stored-secret reuse have backend coverage.
const models = [
  { id: "cloud-dialogue", name: "Modèle dialogue" },
  { id: "cloud-fast", name: "Modèle rapide" },
];

test.afterEach(async ({ request }) => {
  // This server owns a disposable fixture database, never an operator instance.
  if (process.env.E2E_BASE_URL) return;
  const response = await request.get("/api/providers");
  for (const provider of await response.json()) {
    await request.delete(`/api/providers/${provider.id}`);
  }
});

for (const mobile of [false, true]) {
  test(`simple provider setup, saved key and multiple profiles ${mobile ? "mobile" : "desktop"}`, async ({
    page,
  }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const payloads: Record<string, string>[] = [];
    let finishFirst!: () => void;
    const firstReady = new Promise<void>((resolve) => {
      finishFirst = resolve;
    });
    await page.route("**/api/providers/models", async (route) => {
      payloads.push(route.request().postDataJSON());
      if (payloads.length === 1) await firstReady;
      await route.fulfill({ json: { models, truncated: false } });
    });
    await page.goto("/#parametres");
    await page
      .getByRole("button", { name: "Ajouter un fournisseur", exact: true })
      .click();
    let dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Fournisseur", exact: true })
      .selectOption("deepseek");
    await expect(
      dialog.getByLabel("Langue source", { exact: true }),
    ).toHaveCount(0);
    await expect(dialog.getByLabel(/^URL de l’API/)).toHaveCount(0);
    await dialog.getByLabel(/^Clé API/).fill("TEST-ONLY-browser-key");
    await dialog.getByLabel(/^Clé API/).press("Tab");
    await expect(
      dialog.getByText("Lecture des modèles disponibles sur le service…"),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Enregistrer le profil",
        exact: true,
      }),
    ).toBeDisabled();
    finishFirst();
    await dialog
      .getByRole("combobox", { name: "Modèle", exact: true })
      .selectOption("cloud-fast");
    const name = `Atelier ${mobile ? "mobile" : "desktop"}`;
    await dialog.getByLabel(/^Nom du profil/).fill(name);
    await page.screenshot({
      path: `test-results/providers-${mobile ? "mobile" : "desktop"}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await dialog
      .getByRole("button", { name: "Enregistrer le profil", exact: true })
      .click();
    const card = page
      .locator(".provider-card")
      .filter({ has: page.getByRole("heading", { name, exact: true }) });
    await expect(card).toContainText("Clé enregistrée");
    await card
      .getByRole("button", { name: `Modifier ${name}`, exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel(/^Clé API/)).toHaveValue("");
    await dialog
      .getByRole("button", { name: "Charger les modèles", exact: true })
      .click();
    await expect(dialog.getByText("2 modèles reçus du service.")).toBeVisible();
    expect(payloads[1].id).toBeTruthy();
    expect(payloads[1].api_key).toBe("");
    await dialog.getByRole("button", { name: "Annuler", exact: true }).click();
    await page
      .getByRole("button", { name: "Ajouter un fournisseur", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "Fournisseur", exact: true })
      .selectOption("ollama");
    await dialog.getByLabel(/^URL du serveur/).fill("http://127.0.0.1:11434");
    await dialog
      .getByRole("button", { name: "Charger les modèles", exact: true })
      .click();
    await dialog
      .getByRole("combobox", { name: "Modèle", exact: true })
      .selectOption("cloud-dialogue");
    await dialog
      .getByRole("button", { name: "Enregistrer le profil", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Ollama · cloud-dialogue",
        exact: true,
      }),
    ).toBeVisible();
    await expect(card).toBeVisible();
    const response = await page.request.get("/api/providers");
    expect(await response.text()).not.toContain("TEST-ONLY-browser-key");
    expect(
      await page.evaluate(() =>
        JSON.stringify({
          local: { ...localStorage },
          session: { ...sessionStorage },
        }),
      ),
    ).not.toContain("TEST-ONLY-browser-key");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

test("stale catalogue cannot cross providers and manual local setup stays available", async ({
  page,
}) => {
  let finish!: () => void;
  const ready = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let requests = 0;
  await page.route("**/api/providers/models", async (route) => {
    requests += 1;
    if (requests === 1) {
      await ready;
      await route.fulfill({ json: { models, truncated: false } });
    } else {
      await route.fulfill({
        status: 400,
        json: {
          detail:
            "Ce serveur ne propose pas de catalogue. Saisissez un modèle manuellement.",
        },
      });
    }
  });
  await page.goto("/#parametres");
  await page
    .getByRole("button", { name: "Ajouter un fournisseur", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^Clé API/).fill("TEST-ONLY-transient-key");
  await dialog.getByLabel(/^Clé API/).press("Tab");
  await expect(
    dialog.getByText("Lecture des modèles disponibles sur le service…"),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Fournisseur", exact: true })
    .selectOption("custom");
  finish();
  await expect(
    dialog.getByRole("combobox", { name: "Modèle", exact: true }),
  ).toBeDisabled();
  await expect(
    dialog.getByRole("option", { name: /Modèle rapide/ }),
  ).toHaveCount(0);
  await expect(dialog.getByLabel(/^Clé API/)).toHaveValue("");
  await dialog.getByLabel(/^URL du serveur/).fill("http://127.0.0.1:5777/v1");
  await dialog
    .getByRole("button", { name: "Charger les modèles", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "ne propose pas de catalogue",
  );
  await dialog
    .getByRole("button", { name: "Saisir un modèle manuellement", exact: true })
    .click();
  await dialog
    .getByLabel("Identifiant du modèle", { exact: true })
    .fill("sillage-test-only");
  await dialog
    .getByRole("button", { name: "Réglages avancés", exact: true })
    .click();
  await expect(dialog.getByLabel("Langue source", { exact: true })).toHaveValue(
    "en",
  );
  await dialog
    .getByRole("button", { name: "Enregistrer le profil", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Serveur compatible OpenAI · sillage-test-only",
      exact: true,
    }),
  ).toBeVisible();
});

test("model search, empty results and the light form work in a short viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.route("**/api/providers/models", (route) =>
    route.fulfill({
      json: {
        models: Array.from({ length: 12 }, (_, index) => ({
          id: `local-${index}`,
          name: `Modèle local ${index}`,
        })),
        truncated: false,
      },
    }),
  );
  await page.goto("/#parametres");
  await page.getByRole("button", { name: "Activer le thème clair", exact: true }).click();
  await page
    .getByRole("button", { name: "Ajouter un fournisseur", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Fournisseur", exact: true })
    .selectOption("custom");
  await dialog.getByLabel(/^URL du serveur/).fill("http://127.0.0.1:5777/v1");
  await dialog
    .getByRole("button", { name: "Charger les modèles", exact: true })
    .click();
  const search = dialog.getByRole("searchbox", {
    name: "Rechercher un modèle",
    exact: true,
  });
  await search.fill("local-3");
  await dialog
    .getByRole("combobox", { name: "Modèle", exact: true })
    .selectOption("local-3");
  await search.fill("absent-model");
  await expect(
    dialog.getByText("Aucun modèle ne correspond à cette recherche."),
  ).toBeVisible();
  await expect(
    dialog.getByRole("combobox", { name: "Modèle", exact: true }),
  ).toHaveValue("local-3");
  await search.fill("");
  await dialog
    .getByRole("button", { name: "Enregistrer le profil", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/providers-light-short.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1280, height: 1000 });
  await dialog.getByRole("heading", { name: "Connecter un fournisseur", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/providers-light.png", animations: "disabled" });
  await dialog
    .getByRole("button", { name: "Enregistrer le profil", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Serveur compatible OpenAI · local-3",
      exact: true,
    }),
  ).toBeVisible();
});
