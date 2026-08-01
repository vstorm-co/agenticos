import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  FAKE_KEY_HINT,
  FAKE_KEY_LABEL,
  SEEDED_SECRET_HINT,
  SEEDED_SECRET_NAME,
  expectNoRenderedSecret,
  pageHeading,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * The vault: what this organization can authenticate with.
 *
 * The security invariant — that no stored value ever reaches the DOM — is
 * asserted in `refusals.spec.ts` against the whole page. What is checked here is
 * the handling that makes that invariant possible, and the two things a unit
 * test cannot reach: the forms are generated from schemas the server publishes,
 * so what they ask for is only really known once a real catalog has answered;
 * and jsdom cannot open a Radix select, so choosing a provider — which is what
 * decides every field below it — happens only in a browser.
 */

test.describe("Vault", () => {
  test("a stored credential is identified by four characters, not by its value", async ({
    page,
  }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    // Enough to tell two credentials apart, useless to anyone reading over your
    // shoulder. The dots are the whole design.
    await expect(page.getByRole("main").getByText(FAKE_KEY_LABEL).first()).toBeVisible();
    await expect(page.getByText(`····${FAKE_KEY_HINT}`)).toBeVisible();
    await expectNoRenderedSecret(page);
  });

  test("holds secrets as well as provider credentials, and says which is which", async ({
    page,
  }) => {
    // The reason this page is a vault and not a list of API keys: a capability
    // declares that it needs a credential of some kind, and a binding names one
    // of these by id. Nothing in the model resolver ever reads it.
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    // A table row now, not a card, and the service column carries the purpose's
    // human label rather than the raw kind. The purpose is the field a capability
    // binding matches on, so naming the service is what a reader needs; `api_key`
    // was never the interesting half - and it is the same word on both of these
    // rows, which is exactly what makes it useless for telling them apart.
    const secret = page.getByRole("row", { name: new RegExp(SEEDED_SECRET_NAME) });
    await expect(secret).toContainText("Custom service");
    await expect(secret).toContainText(`····${SEEDED_SECRET_HINT}`);

    const key = page.getByRole("row", { name: new RegExp(FAKE_KEY_LABEL) });
    await expect(key).toContainText("OpenAI");
    await expectNoRenderedSecret(page);
  });

  test("the credential field is masked while it is typed", async ({ page }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    // One button and one dialog for every kind of key now: a provider credential
    // is a secret whose *purpose* names the service, so there is no separate
    // "Add credential".
    await page.getByRole("button", { name: "Add key" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Add a secret")).toBeVisible();

    // The family first, then the service - two questions rather than a scroll
    // through thirty-one. Which service decides every field below it.
    await dialog.getByRole("button", { name: /^Model provider/ }).click();
    await dialog.getByLabel(/^(Which one|Service)$/).click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();

    // Masked, not because typing a key is dangerous, but because the field is
    // filled in meetings and on shared screens. The input is generated from the
    // service's own secret schema, and it is `format: "password"` there that
    // decides this — so what is really asserted is that the generator honours it.
    await expect(dialog.getByRole("textbox", { name: /API key/i })).toHaveAttribute(
      "type",
      "password",
    );

    // The dialog states the contract the rest of the suite enforces. If this
    // sentence ever goes away, the promise it makes should have gone away too.
    // Matched as a phrase rather than a sentence: it sits mid-sentence now, and
    // the promise is what matters, not where the clause begins.
    await expect(dialog).toContainText(/cannot be read back/);
  });

  test("asks a provider for the shape of credential it actually takes", async ({ page }) => {
    // The whole point of reading `/providers/catalog` instead of listing four
    // providers in the frontend. Bedrock's credential is an AWS key pair and a
    // region, and there is no version of that which fits in one "API key" box —
    // the old form offered exactly that box for all twenty-four providers.
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add key" }).first().click();
    const dialog = page.getByRole("dialog");

    await dialog.getByRole("button", { name: /^Model provider/ }).click();
    await dialog.getByLabel(/^(Which one|Service)$/).click();
    await page.getByRole("option", { name: "AWS Bedrock" }).click();

    // Labelled from the schema's titles now - "Access key ID", not the raw
    // `aws_access_key_id`. The two secret halves of the pair are password inputs,
    // which have no `textbox` role at all; their reveal buttons are what proves
    // they rendered.
    await expect(dialog.getByRole("textbox", { name: /Access key ID/i })).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: /Region/i })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /Show Secret access key/i })).toBeVisible();

    // The single "API key" box the old form offered for all twenty-four providers
    // is exactly what a key pair does not fit into.
    await expect(dialog.getByRole("textbox", { name: /^API key/i })).toHaveCount(0);
  });

  test("rotating a secret changes its value and keeps its id", async ({ page }) => {
    // The reason rotation is a PATCH and not delete-and-recreate. Every agent
    // binding names a secret by id, so a new row would leave each of them
    // pointing at something this organization no longer has — and would say so
    // only at the next run.
    const name = `e2e-rotate-${Date.now().toString(36)}`;

    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add key" }).first().click();
    const add = page.getByRole("dialog");
    // "Something else" is the generic shape - a bare API key for a service the
    // catalog does not name. Deliberately not a model provider's: a second
    // OpenAI key would change what the Builder's key picker offers, and this
    // spec is about rotation rather than about what a provider key unlocks.
    await add.getByRole("button", { name: /^Something else/ }).click();
    await add.getByLabel("Name").fill(name);
    await add.getByRole("textbox", { name: /API key/i }).fill("sk-e2eROTATEfirstvalueAAAA");
    await add.getByRole("button", { name: "Store secret" }).click();

    const row = () => page.getByRole("row", { name: new RegExp(name) });
    await expect(row()).toContainText("····AAAA");
    const before = await secretId(page, name);

    await page.getByRole("button", { name: `Rotate ${name}` }).click();
    const rotate = page.getByRole("dialog");
    // The dialog has to say what it destroys: somebody who has not written the
    // old value down elsewhere needs to know before they find out.
    await expect(rotate).toContainText("the old one is gone");
    await expect(rotate).toContainText("····AAAA");
    await rotate.getByRole("textbox", { name: /API key/i }).fill("sk-e2eROTATEsecondvalueBBBB");
    await rotate.getByRole("button", { name: "Rotate" }).click();

    await expect(row()).toContainText("····BBBB");
    expect(await secretId(page, name), "rotation replaced the row instead of its value").toBe(
      before,
    );
    await expectNoRenderedSecret(page);

    await page.getByRole("button", { name: `Delete ${name}` }).click();
    await expect(page.getByRole("main").getByText(name)).toHaveCount(0);
  });
});

/**
 * The id the vault holds a secret under, read from the API.
 *
 * Asked of the server rather than of the page, because the id is deliberately
 * not on screen — and it is the one thing a rotation must not change.
 */
async function secretId(page: import("@playwright/test").Page, name: string): Promise<string> {
  const response = await page.request.get("/api/secrets");
  expect(response.ok(), `/api/secrets answered ${response.status()}`).toBe(true);
  const list = (await response.json()) as { items: { id: string; name: string }[] };
  const found = list.items.find((secret) => secret.name === name);
  expect(found, `the vault has no secret called ${name}`).toBeDefined();
  return found!.id;
}
