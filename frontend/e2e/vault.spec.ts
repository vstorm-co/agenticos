import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  FAKE_KEY_HINT,
  FAKE_KEY_LABEL,
  SEEDED_MODEL_ID,
  SEEDED_MODEL_LABEL,
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
  test("lists the model the seed created, and what it points at", async ({ page }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    // An agent references a model by name; the name is worth nothing unless the
    // provider and model id behind it are visible, because that pair is what
    // decides which API is called and what it costs.
    await expect(page.getByRole("main").getByText(SEEDED_MODEL_LABEL).first()).toBeVisible();
    await expect(page.getByText(`openai · ${SEEDED_MODEL_ID}`)).toBeVisible();

    // Bootstrap creates that profile without a credential on purpose, and the
    // page has to say so — an agent that cannot run should look different from
    // one that can, well before somebody finds out at run time. Asserted on that
    // model's own row: "somewhere on this page is the words 'no key'" is also
    // satisfied by a badge belonging to a different model entirely.
    await expect(modelRow(page, SEEDED_MODEL_LABEL)).toContainText("no key");
  });

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

    const secrets = page.getByRole("main").locator("div", { hasText: SEEDED_SECRET_NAME }).last();
    await expect(secrets).toContainText("api_key");
    await expect(secrets).toContainText(`····${SEEDED_SECRET_HINT}`);
    await expectNoRenderedSecret(page);
  });

  test("the credential field is masked while it is typed", async ({ page }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add credential" }).click();
    const dialog = page.getByRole("dialog");

    // Nothing is preselected, because the provider decides every field below it
    // and a default is how an OpenAI key gets stored under another provider.
    await expect(dialog.getByLabel("Provider")).toHaveText("Choose a provider");
    await expect(dialog.getByRole("button", { name: "Store credential" })).toBeDisabled();

    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();

    // Masked, not because typing a key is dangerous, but because the field is
    // filled in meetings and on shared screens. The input is generated from the
    // provider's own secret schema, and it is `format: "password"` there that
    // decides this — so what is really asserted is that the generator honours it.
    await expect(dialog.getByLabel(/Api Key/)).toHaveAttribute("type", "password");

    // The dialog states the contract the rest of the suite enforces. If this
    // sentence ever goes away, the promise it makes should have gone away too.
    await expect(dialog).toContainText("It cannot be read back");
  });

  test("asks a provider for the shape of credential it actually takes", async ({ page }) => {
    // The whole point of reading `/providers/catalog` instead of listing four
    // providers in the frontend. Bedrock's credential is an AWS key pair and a
    // region, and there is no version of that which fits in one "API key" box —
    // the old form offered exactly that box for all twenty-four providers.
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add credential" }).click();
    const dialog = page.getByRole("dialog");

    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "AWS Bedrock" }).click();

    await expect(dialog.getByLabel(/Aws Access Key Id/)).toBeVisible();
    await expect(dialog.getByLabel(/Region Name/)).toBeVisible();
    await expect(dialog.getByLabel(/^Api Key/)).toHaveCount(0);

    // Bedrock is reached at its own endpoint, so a custom one would be ignored
    // and the backend refuses to store it. A setting that does nothing is worse
    // than an error, so it is not offered at all.
    await expect(dialog.getByLabel(/Endpoint/)).toHaveCount(0);
  });

  test("stores a local server with no key at all, which is what keyless is for", async ({
    page,
  }) => {
    const label = `e2e-keyless-${Date.now().toString(36)}`;

    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add credential" }).click();
    const dialog = page.getByRole("dialog");

    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "Ollama" }).click();
    await dialog.getByLabel("Label").fill(label);

    // Ollama on a machine of your own has nothing to authenticate against, and
    // demanding a token here is demanding that somebody invent one.
    await dialog.getByRole("switch", { name: /needs no key/ }).click();
    await expect(dialog.getByLabel(/^Api Key/)).toHaveCount(0);

    // Still refused until it says where to reach the server: a credential with
    // no key and no address is one aimed at the vendor's public API with nothing
    // behind it, and the backend rejects it.
    await expect(dialog.getByRole("button", { name: "Store credential" })).toBeDisabled();

    // A resolvable public host, because this deployment has
    // ALLOW_INTERNAL_MODEL_ENDPOINTS off — which is the default, and which the
    // spec below is about. What is being proved here is the keyless path, not
    // the address policy.
    await dialog.getByLabel(/Endpoint/).fill("https://example.com/v1");
    await dialog.getByRole("button", { name: "Store credential" }).click();

    const row = page.getByRole("main").locator("div", { hasText: label }).last();
    await expect(row).toContainText("no key");
    await expect(row).toContainText("https://example.com/v1");

    // Reloaded, because a row that exists only in the mutation's cache patch is
    // a row that was never written.
    await page.reload();
    await expect(pageHeading(page, "Vault")).toBeVisible();
    await expect(page.getByRole("main").getByText(label)).toBeVisible();

    await page.getByRole("button", { name: `Delete ${label}` }).click();
    await expect(page.getByRole("main").getByText(label)).toHaveCount(0);
  });

  test("a refused endpoint is reported under the endpoint, in the server's own words", async ({
    page,
  }) => {
    // Every `base_url` check reports the URL it refused, and this is the whole
    // journey for one of them: the browser sends it, the service refuses it, the
    // proxy carries the refusal back with its body intact, and the dialog puts
    // the sentence under the input that produced it rather than in a toast that
    // takes it away again.
    //
    // The scheme check is used rather than the internal-address one because it
    // applies either way: whether an internal address is refused depends on
    // ALLOW_INTERNAL_MODEL_ENDPOINTS, and a spec that fails on a legitimate
    // configuration is a spec people learn to re-run instead of read. That
    // message — the one naming the setting — is asserted in the unit tests.
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add credential" }).click();
    const dialog = page.getByRole("dialog");

    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "Ollama" }).click();
    await dialog.getByLabel("Label").fill(`e2e-refused-${Date.now().toString(36)}`);
    await dialog.getByRole("switch", { name: /needs no key/ }).click();
    await dialog.getByLabel(/Endpoint/).fill("file:///etc/passwd");
    await dialog.getByRole("button", { name: "Store credential" }).click();

    await expect(dialog.getByText(/must be an http or https URL/)).toBeVisible();
    // Still open, with what was typed still in it. A dialog that closed on a
    // refusal would throw away the thing that needs correcting.
    await expect(dialog.getByLabel(/Endpoint/)).toHaveValue("file:///etc/passwd");
  });

  test("rotating a secret changes its value and keeps its id", async ({ page }) => {
    // The reason rotation is a PATCH and not delete-and-recreate. Every agent
    // binding names a secret by id, so a new row would leave each of them
    // pointing at something this organization no longer has — and would say so
    // only at the next run.
    const name = `e2e-rotate-${Date.now().toString(36)}`;

    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add secret" }).click();
    const add = page.getByRole("dialog");
    await add.getByLabel("Name").fill(name);
    await add.getByLabel(/Api Key/).fill("sk-e2eROTATEfirstvalueAAAA");
    await add.getByRole("button", { name: "Store secret" }).click();

    const row = () => page.getByRole("main").locator("div", { hasText: name }).last();
    await expect(row()).toContainText("····AAAA");
    const before = await secretId(page, name);

    await page.getByRole("button", { name: `Rotate ${name}` }).click();
    const rotate = page.getByRole("dialog");
    // The dialog has to say what it destroys: somebody who has not written the
    // old value down elsewhere needs to know before they find out.
    await expect(rotate).toContainText("the old one is gone");
    await expect(rotate).toContainText("····AAAA");
    await rotate.getByLabel(/Api Key/).fill("sk-e2eROTATEsecondvalueBBBB");
    await rotate.getByRole("button", { name: "Rotate" }).click();

    await expect(row()).toContainText("····BBBB");
    expect(await secretId(page, name), "rotation replaced the row instead of its value").toBe(
      before,
    );
    await expectNoRenderedSecret(page);

    await page.getByRole("button", { name: `Delete ${name}` }).click();
    await expect(page.getByRole("main").getByText(name)).toHaveCount(0);
  });

  test("a model cannot be created without a name and a model id", async ({ page }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add model" }).click();

    const dialog = page.getByRole("dialog");
    const submit = dialog.getByRole("button", { name: "Add model" });
    await expect(submit).toBeDisabled();

    await dialog.getByLabel("Name").fill("E2E model");
    // Still refused: an agent references a model by name, and a named model
    // pointing at nothing fails at the moment a run needs it instead of here.
    await expect(submit).toBeDisabled();

    await dialog.getByLabel("Model id").fill("gpt-4.1-mini");
    // And still refused, because a model with no provider is a model nothing
    // can resolve. Nothing is preselected here either.
    await expect(submit).toBeDisabled();

    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();
    await expect(submit).toBeEnabled();
  });

  test("a model bound to a stored credential comes back bound", async ({ page }) => {
    const label = `e2e-model-${Date.now().toString(36)}`;

    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    await page.getByRole("button", { name: "Add model" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();
    await dialog.getByLabel("Name").fill(label);
    await dialog.getByLabel("Model id").fill("gpt-4.1-mini");

    // The picker lists the credentials stored *for this provider*, by label.
    // Choosing one is what proves the credential list on this page came out of
    // the vault rather than out of an empty array the UI shrugged off.
    await dialog.getByRole("combobox").filter({ hasText: "Choose a key" }).click();
    await page.getByRole("option", { name: new RegExp(FAKE_KEY_LABEL) }).click();
    await dialog.getByRole("button", { name: "Add model" }).click();

    await expect(page.getByRole("main").getByText(label)).toBeVisible();

    // Reloaded, because a row that exists only in the mutation's cache patch is
    // a row that was never written.
    await page.reload();
    await expect(pageHeading(page, "Vault")).toBeVisible();
    await expect(page.getByRole("main").getByText(label)).toBeVisible();
    await expect(page.getByRole("main")).toContainText("openai · gpt-4.1-mini");
    await expectNoRenderedSecret(page);

    await page.getByRole("button", { name: `Delete ${label}` }).click();
    await expect(page.getByRole("main").getByText(label)).toHaveCount(0);
  });
});

/**
 * The row one model profile occupies, found by the label printed on it.
 *
 * The innermost matching element, because every card and section above it also
 * contains the label — and a badge asserted against the whole page is a badge
 * that may belong to any other row.
 */
function modelRow(page: import("@playwright/test").Page, label: string) {
  return page.getByRole("main").locator("div", { hasText: label }).last();
}

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
