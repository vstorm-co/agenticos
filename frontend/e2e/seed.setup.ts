import { test as setup, expect, type APIRequestContext, type Page } from "@playwright/test";

import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  COLLEAGUE_PASSWORD,
  DRAFT_AGENT_SLUG,
  DRAFT_AGENT_NAME,
  FAKE_KEY_LABEL,
  FAKE_KEY_SECRET,
  SEEDED_KB_NAME,
  SEEDED_SECRET_NAME,
  SEEDED_SECRET_VALUE,
  SEEDED_ORG_MCP_NAME,
  SEEDED_ORG_MCP_SECRET,
  SEEDED_ORG_MCP_URL,
  SEEDED_SKILL_CONTENT,
  SEEDED_SKILL_DESCRIPTION,
  SEEDED_SKILL_NAME,
  pageHeading,
  skillCard,
} from "./helpers";

/**
 * The fixtures `agenticos cmd bootstrap` does not create.
 *
 * Bootstrap walks a fresh install to *one published agent* and stops there, on
 * purpose — it is the shortest path to seeing the product work, not a demo
 * database. That leaves the rest of the suite with nothing to assert on, and a
 * spec with nothing to assert on quietly becomes a spec that asserts on chrome.
 *
 * So everything else is created here, through the product: a skill, a knowledge
 * base, a draft agent, both halves of the vault (a provider credential and a
 * secret) and a second member. Each step checks
 * before it creates, because this runs against a database that may already have
 * been through it — and a setup that fails the second time you run it is a
 * setup people learn to skip.
 *
 * Two things use the HTTP API rather than the UI, and only because the UI has
 * no path for them: registering the colleague (their first sign-in has to
 * happen before they can be invited anywhere), and reading the invitation token
 * off the reply to sending it (it is emailed, the inviter's screen deliberately
 * never prints it, and a test has no inbox).
 */

setup.use({ storageState: AUTH_STATE });

setup("a skill exists", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/skills", "name", SEEDED_SKILL_NAME)) return;

  await page.goto("/skills");
  await expect(pageHeading(page, "Skills")).toBeVisible();

  // The header action and the empty state's call to action are the same button.
  await page.getByRole("button", { name: "New skill" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(SEEDED_SKILL_NAME);
  await dialog.getByLabel("Description").fill(SEEDED_SKILL_DESCRIPTION);
  // The body is `SKILL.md` in a file tree now, not a "Content" textarea - the
  // create dialog was rebuilt to look like the editor a skill becomes. It opens
  // in Preview, where there is no input at all, so switch to Source first; the
  // textarea then takes its accessible name from the file it is showing.
  await dialog.getByRole("button", { name: "Source" }).click();
  await dialog.getByLabel(/SKILL\.md source/).fill(SEEDED_SKILL_CONTENT);
  await dialog.getByRole("button", { name: "Create" }).click();

  await expect(skillCard(page, SEEDED_SKILL_NAME)).toBeVisible();
});

setup("a knowledge base exists", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/kb", "name", SEEDED_KB_NAME)) return;

  await page.goto("/rag");
  await expect(pageHeading(page, "Knowledge bases")).toBeVisible();

  await page.getByRole("button", { name: "New knowledge base" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(SEEDED_KB_NAME);
  await dialog.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByText(SEEDED_KB_NAME, { exact: true }).first()).toBeVisible();
});

setup("a draft agent exists", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/agents", "slug", DRAFT_AGENT_SLUG)) return;

  await page.goto("/agents");
  await expect(pageHeading(page, "Agents")).toBeVisible();

  await page.getByRole("button", { name: "New agent" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(DRAFT_AGENT_NAME);
  await dialog.getByRole("button", { name: "Create", exact: true }).click();

  // Creating navigates straight into the Builder for the new draft.
  await expect(pageHeading(page, new RegExp(DRAFT_AGENT_NAME))).toBeVisible();
});

/**
 * Store one secret through the Vault's dialog.
 *
 * There is one dialog and one button for every kind of key now. A provider
 * credential is not a separate resource with its own endpoint - it is a secret
 * whose *purpose* says which service it is for, which is why both callers below
 * differ only in the group they pick and the name they give it.
 *
 * `/api/providers/credentials` is what the idempotency check used to poll. That
 * route never existed after provider keys moved into the vault, so the check
 * asserted on a 404 and this step failed before touching the UI.
 */
async function storeSecret(
  page: Page,
  { group, service, name, value }: { group: string; service?: string; name: string; value: string },
) {
  await page.goto("/vault");
  await expect(pageHeading(page, "Vault")).toBeVisible();

  await page.getByRole("button", { name: "Add key" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Add a secret")).toBeVisible();

  // Two steps rather than one list of thirty-one: the family first, which rules
  // out most of the second question.
  await dialog.getByRole("button", { name: new RegExp(`^${group}`) }).click();
  if (service) {
    await dialog.getByLabel(/^(Which one|Service)$/).click();
    await page.getByRole("option", { name: service, exact: true }).click();
  }

  await dialog.getByLabel("Name").fill(name);
  // Generated from the chosen service's own secret schema, so it is named by the
  // schema rather than by this form - "API key", and marked required, so the
  // match has to be loose at both ends. Scoped to the textbox because the
  // reveal button beside it is named "Show API key" and matches too.
  await dialog.getByRole("textbox", { name: /API key/i }).fill(value);
  await dialog.getByRole("button", { name: "Store secret" }).click();

  await expect(page.getByRole("main").getByText(name)).toBeVisible();
}

setup("a provider key is stored", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/secrets", "name", FAKE_KEY_LABEL)) return;

  // OpenAI specifically: the specs assert this key is a model provider's, and
  // which provider decides what `add-model` offers.
  await storeSecret(page, {
    group: "Model provider",
    service: "OpenAI",
    name: FAKE_KEY_LABEL,
    value: FAKE_KEY_SECRET,
  });
});

setup("a secret is stored", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/secrets", "name", SEEDED_SECRET_NAME)) return;

  // "Something else" twice over - the family, and then the purpose inside it.
  // The family alone falls through to the first service in it (LlamaParse), and
  // a key with a named service is offered only to a capability configured for
  // that service. `custom` is the purpose that fits any of them, which is what a
  // capability binding needs to exist without this seed having to know which
  // search provider a spec will pick.
  await storeSecret(page, {
    group: "Something else",
    service: "Something else",
    name: SEEDED_SECRET_NAME,
    value: SEEDED_SECRET_VALUE,
  });
});

setup("the organization has connected an MCP server", async ({ page }) => {
  if (await alreadyThere(page.request, "/api/mcp-connections", "name", SEEDED_ORG_MCP_NAME)) {
    return;
  }

  await page.goto("/mcp-servers");
  await expect(pageHeading(page, "MCP servers")).toBeVisible();

  // The page is a catalog now, so a server that is not in it is reached through
  // the custom entry rather than through one "add" button.
  await page.getByRole("button", { name: "Add a custom server" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(SEEDED_ORG_MCP_NAME);
  await dialog.getByLabel("Server URL").fill(SEEDED_ORG_MCP_URL);
  await dialog.getByLabel("Access token").fill(SEEDED_ORG_MCP_SECRET);
  await dialog.getByRole("button", { name: "Connect & check" }).click();

  // Asserted through the API, not by looking for the row. The page is a
  // paginated catalog of every connectable server, so a custom connection is not
  // reliably on the first page - and this step's job is that the fixture exists,
  // not that it is visible from here. `mcp-servers.spec.ts` is what tests
  // whether a connected server the catalog does not carry shows up.
  //
  // The probe behind "Connect & check" dials a host that answers 405, so the
  // connection is stored with an error status. That is the correct outcome for a
  // fixture; a red dot is not a failed seed.
  await expect
    .poll(() => alreadyThere(page.request, "/api/mcp-connections", "name", SEEDED_ORG_MCP_NAME), {
      message: "the organization MCP connection was never stored",
    })
    .toBe(true);
});

setup("a colleague is a member of the organization", async ({ page, browser }) => {
  const organizationId = await activeOrganizationId(page.request);

  const members = await json<{ items: { email: string }[] }>(
    page.request,
    `/api/orgs/${organizationId}/members`,
  );
  if (members.items.some((member) => member.email === COLLEAGUE_EMAIL)) return;

  await registerColleague(page.request);
  const token = await ensurePendingInvitation(page, organizationId);
  await acceptAsColleague(browser, token);

  const after = await json<{ items: { email: string }[] }>(
    page.request,
    `/api/orgs/${organizationId}/members`,
  );
  expect(
    after.items.map((member) => member.email),
    "the colleague accepted the invitation but is not a member",
  ).toContain(COLLEAGUE_EMAIL);
});

/**
 * Whether a row with this value is already in a collection.
 *
 * Asked of the API rather than of the page, because `Locator.count()` does not
 * wait: a list that had not arrived yet reads as a list with nothing in it, and
 * a setup built on that answer creates a duplicate every time it runs. This one
 * seeded six knowledge bases before it was noticed.
 */
async function alreadyThere(
  request: APIRequestContext,
  path: string,
  field: string,
  value: string,
): Promise<boolean> {
  const list = await json<{ items: Record<string, unknown>[] }>(request, path);
  return list.items.some((item) => item[field] === value);
}

/** A JSON GET that fails loudly, so a broken fixture reads as a broken fixture. */
async function json<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

/** The organization the seeded owner works in — bootstrap reuses their personal one. */
async function activeOrganizationId(request: APIRequestContext): Promise<string> {
  const orgs = await json<{ items: { id: string }[] }>(request, "/api/orgs");
  const first = orgs.items[0];
  expect(first, "the owner belongs to no organization; was bootstrap run?").toBeDefined();
  return first!.id;
}

/**
 * Register the colleague. Idempotent: a second run finds the account already
 * there, which the API reports as a 4xx rather than a surprise.
 */
async function registerColleague(request: APIRequestContext): Promise<void> {
  const response = await request.post("/api/auth/register", {
    data: {
      email: COLLEAGUE_EMAIL,
      password: COLLEAGUE_PASSWORD,
      full_name: "Colleague",
    },
  });
  expect(
    response.ok() || response.status() === 400 || response.status() === 409,
    `registering the colleague answered ${response.status()}`,
  ).toBe(true);
}

/**
 * The token of a fresh pending invitation for the colleague.
 *
 * The token is read from the response to *sending* the invitation, because that
 * is the only reply that carries one: listing an organization's invitations
 * deliberately returns everything except the token, since a token is a bearer
 * credential and the list is on screen for every admin. The invitation itself
 * is still sent the way an owner sends it, from the members page, because that
 * is a flow worth exercising rather than stubbing.
 *
 * A leftover pending invitation from a half-finished run is revoked rather than
 * reused — its token is not recoverable, and a second invitation to the same
 * address is refused as a duplicate.
 */
async function ensurePendingInvitation(page: Page, organizationId: string): Promise<string> {
  await revokeAnyPendingInvitation(page, organizationId);

  await page.goto(`/orgs/${organizationId}/members`);
  await page.getByRole("button", { name: "Invite teammate" }).first().click();

  const sent = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/orgs/${organizationId}/invitations`) &&
      response.request().method() === "POST",
  );

  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email address").fill(COLLEAGUE_EMAIL);
  await dialog.getByRole("button", { name: "Send invite" }).click();
  // The dialog only closes when the invitation was accepted by the server.
  await expect(dialog).toBeHidden();

  const body = (await (await sent).json()) as { invitation_token?: string };
  expect(body.invitation_token, "sending the invitation returned no token").toBeDefined();
  return body.invitation_token!;
}

/** Withdraw a pending invitation left by an earlier run, addressing it by id. */
async function revokeAnyPendingInvitation(page: Page, organizationId: string): Promise<void> {
  const invitations = await json<{ items: { id: string; email: string; status: string }[] }>(
    page.request,
    `/api/orgs/${organizationId}/invitations`,
  );
  const pending = invitations.items.find(
    (invitation) => invitation.email === COLLEAGUE_EMAIL && invitation.status === "pending",
  );
  if (!pending) return;

  const response = await page.request.delete(
    `/api/orgs/${organizationId}/invitations/${pending.id}`,
  );
  expect(response.ok(), `revoking the stale invitation answered ${response.status()}`).toBe(true);
}

/** Sign in as the colleague in their own context and accept, as they would. */
async function acceptAsColleague(
  browser: import("@playwright/test").Browser,
  token: string,
): Promise<void> {
  const context = await browser.newContext();
  try {
    const colleague = await context.newPage();

    await colleague.goto("/login");
    await colleague.getByLabel("Email").fill(COLLEAGUE_EMAIL);
    await colleague.getByLabel("Password").fill(COLLEAGUE_PASSWORD);
    await colleague.getByRole("button", { name: "Login" }).click();
    await expect(colleague).toHaveURL(/\/dashboard(\?.*)?$/);

    await colleague.goto(`/invitations/${token}`);
    await colleague.getByRole("button", { name: "Accept invitation" }).click();
    await expect(colleague.getByText("You joined the organization!")).toBeVisible();
  } finally {
    await context.close();
  }
}
