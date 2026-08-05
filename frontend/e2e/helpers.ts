import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Shared vocabulary for the E2E suite.
 *
 * Not a `.spec.ts`, so Playwright never collects it as a test file.
 */

/**
 * The signed-in session written by `auth.setup.ts`.
 *
 * Every dashboard route sits behind `AuthGuard`. A spec that forgets this is
 * redirected to /login and then fails on a missing heading — a confusing way to
 * learn that the test, not the page, was misconfigured.
 */
export const AUTH_STATE = ".playwright/.auth/user.json";

/**
 * The owner `agenticos cmd bootstrap` creates.
 *
 * The whole suite asserts against that seed rather than against whatever
 * happens to be in the database, because "the list rendered" and "the list
 * rendered nothing because the request failed" are the same screen. Anything
 * the seed does not create is created by `seed.setup.ts`, through the UI.
 */
export const OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "admin@example.com";
export const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "admin123";

/** The published agent bootstrap leaves behind, by name and by handle. */
export const SEEDED_AGENT_NAME = "Getting Started";
export const SEEDED_AGENT_HANDLE = "@getting-started";
/** The default model profile bootstrap creates, and the model it points at. */
export const SEEDED_MODEL_LABEL = "openai default";
export const SEEDED_MODEL_ID = "gpt-4.1";

/* ------------------------------------------------------------------ *
 * Fixtures `seed.setup.ts` creates through the UI, because bootstrap  *
 * does not. Named as constants so a spec asserts on the same string   *
 * the setup typed.                                                    *
 * ------------------------------------------------------------------ */

/** A skill, so the gallery has a row and the editor has something to open. */
export const SEEDED_SKILL_NAME = "e2e-refund-policy";
export const SEEDED_SKILL_DESCRIPTION = "How refunds and their exceptions are handled.";
export const SEEDED_SKILL_CONTENT = "## When a customer asks for a refund\n\nCheck the order date.";

/** A knowledge base, so /kb has a row rather than only an empty state. */
export const SEEDED_KB_NAME = "E2E Handbook";

/** A draft agent: the only thing that can prove an unpublished agent will not run. */
export const DRAFT_AGENT_NAME = "E2E Draft";
export const DRAFT_AGENT_SLUG = "e2e-draft";
export const DRAFT_AGENT_HANDLE = `@${DRAFT_AGENT_SLUG}`;

/**
 * A capability that exposes tools, and the tool it exposes.
 *
 * Per-tool approval can only be proved against a capability that has tools, and
 * the one bootstrap puts on the seeded agent (`clock`) deliberately has none —
 * it writes the time into the instructions. Knowledge search is registered in
 * code rather than seeded, so it is in every deployment's catalog, and the tool
 * name is the one its toolset registers.
 */
export const CAPABILITY_WITH_TOOLS = "Knowledge search";
export const CAPABILITY_TOOL = "search_documents";

/**
 * What the Builder renames that tool to, and back from.
 *
 * A name the model would treat differently rather than a nonsense string: the
 * feature exists because `search_refund_policy` is reached for on questions
 * `search_documents` is passed over for.
 */
export const RENAMED_TOOL = "search_refund_policy";

/**
 * A second member, so a grant has somebody to be granted to.
 *
 * Sharing's whole promise is that it lifts one person's access to one row. In a
 * single-member organization that promise cannot be exercised at all, only
 * described.
 */
export const COLLEAGUE_EMAIL = "colleague@example.com";
export const COLLEAGUE_PASSWORD = "ColleaguePassword123!";

/**
 * A stored provider credential that is deliberately not a working one.
 *
 * Nothing calls a model with it — its only job is to exist, so the pages that
 * join credentials into other data have a credential to leak. A page swept for
 * secrets while no secret is stored proves nothing.
 */
export const FAKE_KEY_LABEL = "e2e-vault-probe";
export const FAKE_KEY_SECRET = "sk-e2eFAKEnotarealkeyatall9XZ7";
export const FAKE_KEY_HINT = "9XZ7";

/**
 * A stored secret, which is the other half of the vault and not a provider key.
 *
 * A capability binds one of these by id, so it is what proves the vault holds
 * more than the credentials the model resolver reads — and it is the only row
 * that can be rotated, since there is no PATCH for a provider credential.
 */
export const SEEDED_SECRET_NAME = "e2e-capability-token";
export const SEEDED_SECRET_VALUE = "sk-e2eSECRETnotarealtokenP7KD";
export const SEEDED_SECRET_HINT = "P7KD";

/**
 * An MCP server the organization owns, and the credential sealed with it.
 *
 * It exists for two assertions that need a row rather than an empty state: that
 * the Builder offers the organization's servers (and only those), and that a
 * page joining connections into anything else does not render the token.
 *
 * The URL is never dialled, but it *is* resolved: the SSRF check refuses a
 * hostname it cannot look up at all, not only a private one, so this has to be a
 * name that exists. It used to be `mcp.example.com`, which does not — nothing
 * under `example.com` resolves except the apex — and this fixture failed on that
 * for every run, taking the whole seed and every spec depending on it with it.
 */
export const SEEDED_ORG_MCP_NAME = "e2e-org-server";
export const SEEDED_ORG_MCP_URL = "https://example.com/mcp";
export const SEEDED_ORG_MCP_SECRET = "sk-e2eORGmcpnotarealtoken4KQ2";

/**
 * What a provider secret looks like once it has reached the page.
 *
 * The prefix plus the length is specific enough that a match is a leak rather
 * than a coincidence: no label, model id or trace id in this product looks like
 * this.
 */
export const RENDERED_SECRET = /sk-[A-Za-z0-9]{20,}/;

/** The page's own title, as `PageHeader` renders it. */
export function pageHeading(page: Page, name?: string | RegExp): Locator {
  return page.getByRole("heading", { level: 1, name });
}

/**
 * Submit a dialog, and do not return until the page has acted on what it wrote.
 *
 * This replaces `click(submit)` followed straight away by
 * `expect(theNewRow).toBeVisible()`. That shape sat at six sites, was seen to
 * flake at four of them, and cost three separate diagnoses (#132) — always with
 * the same useless message, `element(s) not found`, sixteen seconds later.
 *
 * The message is why it cost three. **An open Radix dialog takes the rest of the
 * page out of the accessibility tree**: while one is on screen,
 * `page.getByRole("main")`, `getByRole("row")` and `skillCard()` resolve to
 * *nothing at all*, whether or not the row they are looking for exists. So the
 * assertion that timed out could only ever have reported the absence of the
 * page, and it named the one thing that was certainly not the cause. Proved with
 * a probe: `main` counts 1 before the dialog opens, 0 while it is open, and 1
 * again 87ms later — in the same sample that first sees the new row.
 *
 * Two things are waited on, and both are signals rather than hopes:
 *
 * 1. **The write's own response.** Its status and body are the diagnosis the old
 *    shape never printed. A refused create now reads `409 … name already in
 *    use`; a submit that never reached the network reads as a missing response
 *    rather than as a missing row.
 * 2. **The dialog closing.** Every one of these dialogs closes only after the app
 *    has finished the work it does around the write: five of the six write
 *    through a `useMutation` whose `onSuccess` *awaits* `invalidateQueries`, and
 *    TanStack resolves `mutateAsync` only once that callback has returned; the
 *    knowledge base is the exception, where `useKnowledgeBases.createKB` writes
 *    the row into the cache with `setQueryData` and the dialog closes after that.
 *    Either way an open dialog means the app is not done, and waiting for it to
 *    shut is what stops a spec asserting into the middle of a mutation.
 *
 * **What this does not promise, and cannot:** that the row is now on the page.
 * The list's refetch can be answered with the pre-write list even though the row
 * is committed and both server layers return it — about once in eight runs, and
 * filed as #230. So a closed dialog is the app saying it is finished, not proof
 * that it finished correctly, and a caller that needs the row rendered must
 * either be a spec whose subject *is* that rendering (and take #230's flake, or
 * reload first, as `vault.spec.ts` does) or ask the API instead (as every step of
 * `seed.setup.ts` now does, because a fixture step's job is that the fixture
 * exists).
 *
 * The list's own `GET` is deliberately not waited on as a third step. The
 * knowledge base never makes one, so a caller waiting for it would hang — and
 * where one is made, waiting for it buys nothing the dialog does not already
 * give, since #230 is about the answer being wrong rather than late.
 */
export async function submitDialog(
  page: Page,
  {
    dialog,
    submit,
    path,
    method = "POST",
  }: {
    /** The dialog being submitted. Its closing is the signal, so it is waited on. */
    dialog: Locator;
    /** The button that submits it, as a locator — each caller keeps its own match. */
    submit: Locator;
    /** Where the write goes, as a path prefix: `/api/secrets` also matches a PATCH to one. */
    path: string;
    method?: "POST" | "PATCH";
  },
): Promise<void> {
  // Registered before the click, not after: a fast answer can arrive before
  // `click()` has returned, and a listener attached afterwards would then sit
  // waiting for a second write that nobody is going to make.
  const answered = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.startsWith(path) &&
      response.request().method() === method &&
      // A 401 on this path is not the answer. `apiClient.send` recovers from an
      // expired access token by refreshing and re-issuing the same write, so the
      // app acts on the *retry* — and a helper that stopped at the first response
      // would fail a write that succeeded, which is precisely the class of flake
      // this exists to remove. A refresh that itself fails makes no second write,
      // so that arrives as a missing response and the `/api/auth/refresh` line in
      // the trace is what names it.
      response.status() !== 401,
    // Matched to `expect.timeout` rather than left at Playwright's 30s. A submit
    // that never reached the network should be reported no slower than the
    // assertion this replaces reported nothing at all.
    { timeout: 15_000 },
  );

  await submit.click();

  const response = await answered;
  if (!response.ok()) {
    // The body is read only here, and the guard is what makes that possible:
    // `text()` throws outright on a redirect, so a message built eagerly would
    // replace the diagnosis with a worse one than the shape this replaces had.
    expect(
      response.ok(),
      `${method} ${new URL(response.url()).pathname} answered ${response.status()}: ${await response.text()}`,
    ).toBe(true);
  }

  await expect(
    dialog,
    "the write was accepted but the dialog stayed open, so the page never finished acting on it",
  ).toBeHidden();
}

/**
 * Fail if a provider secret is reachable anywhere in the current page.
 *
 * The platform's promise is that a stored key can never be read back — not by
 * the API and not by the UI. That promise is only worth something if it is
 * checked, because the failure mode is silent: a key rendered in full looks
 * exactly like a key rendered correctly until someone reads it.
 */
export async function expectNoRenderedSecret(page: Page): Promise<void> {
  await expect(page.locator("body")).not.toContainText(RENDERED_SECRET);

  // Visible text is only half of it. A key parked in an attribute, a data-*
  // payload or the serialized server props is just as readable to anyone who
  // opens devtools, and none of that appears in textContent.
  expect(await page.content()).not.toMatch(RENDERED_SECRET);
}

/**
 * The card for one agent on /agents, found by the handle printed on it.
 *
 * The card *root* rather than its link, because callers assert on what the card
 * shows — the name, the status badge — and those are siblings of the link, not
 * inside it.
 *
 * That is also why this cannot be `a[href^="/agents/"]` filtered by text, which
 * is what it used to be and matched nothing: the anchor is an empty `absolute
 * inset-0` overlay whose only accessible name is its `aria-label`, and every
 * word on the card is printed by a sibling. Nine of this suite's eleven agent
 * specs were failing on it. Anchoring on `:has(> a[href^="/agents/"])` picks out
 * exactly the card roots, since the overlay is a direct child of one.
 */
export function agentCard(page: Page, text: string): Locator {
  return page.locator('div:has(> a[href^="/agents/"])').filter({ hasText: text });
}

/**
 * Open the Builder for the agent whose card shows `handle`.
 *
 * Asserting the card is visible first is what makes the click meaningful: it
 * fails on "the agent list is empty" rather than timing out on a click, which
 * is the difference between a readable failure and a mystery.
 *
 * The click targets the overlay link rather than the card, because the card's
 * footer carries Edit, Duplicate and Archive buttons — a click aimed at the
 * container is one layout change away from opening a menu instead.
 */
export async function openAgent(page: Page, name: string): Promise<void> {
  await page.goto("/agents");
  await expect(pageHeading(page, "Agents")).toBeVisible();
  const card = agentCard(page, name);
  await expect(card).toBeVisible();
  await card.getByRole("link", { name: `Open ${name}`, exact: true }).click();
  await expect(pageHeading(page)).toContainText(name);
}

/**
 * Move the Builder to one of its tabs.
 *
 * The Builder is seven tabs now, not one column: capabilities and MCP servers
 * are under Toolbox, sharing and channels under Availability, versions under
 * History. A spec that reaches straight for a control times out on a panel that
 * simply is not mounted, which reads like the control was removed.
 */
export async function openBuilderTab(page: Page, name: string): Promise<void> {
  await page.getByRole("tab", { name, exact: true }).click();
}

/** The Builder's own word for "what is on screen is not what the server holds". */
export function unsaved(page: Page): Locator {
  return page.getByText("unsaved");
}

/**
 * Wait until the Builder has stored the draft.
 *
 * There is no Save button - the draft stores itself 1.2s after the last edit -
 * and that is a trap for a spec rather than for a person: anything that reloads
 * the page before the timer fires reloads the draft the edit replaced, and the
 * assertion that follows describes the wrong state. The badge going quiet is the
 * only signal the product gives that the two agree, so it is what this waits on.
 */
export async function saveDraft(page: Page): Promise<void> {
  await expect(
    unsaved(page),
    "the Builder still says the draft is unsaved, so nothing below is reading what the API stored",
  ).toBeHidden();
}

/**
 * The card for one skill in the gallery.
 *
 * A card is a button labelled by the skill's own name and description — there
 * is no heading or test id to aim at. Anchoring the name to the start is what
 * separates it from the icon-only delete button beside it, whose accessible
 * name is "Delete <the same skill>".
 */
export function skillCard(page: Page, name: string): Locator {
  return page.getByRole("main").getByRole("button", { name: new RegExp(`^${name}\\b`) });
}

/**
 * Navigate to the permission matrix of the first organization the user belongs
 * to.
 *
 * It used to return false when no organization was on screen, so callers could
 * skip. That guard was reached far more often than it was true: `count()` does
 * not wait, so an organization list that had simply not arrived yet read as an
 * organization that did not exist, and the tests behind it skipped themselves
 * green. The seeded owner always has one, so this waits and fails instead.
 */
export async function gotoRoleMatrix(page: Page): Promise<void> {
  await page.goto("/orgs");
  await expect(pageHeading(page, "Organizations")).toBeVisible();

  // The whole card is the link now, labelled "Open <name>", and it lands on the
  // members page directly - there is no intermediate "Manage" button. The
  // "Switch" / "Current" button beside it changes the active organization rather
  // than navigating, which is why the link carries its own accessible name.
  const open = page.getByRole("link", { name: /^Open / }).first();
  await expect(open, "the seeded owner has no organization; was bootstrap run?").toBeVisible();

  await open.click();
  // The card lands on the organization, whose own nav carries Roles.
  await page.getByRole("link", { name: "Roles" }).click();
  await expect(pageHeading(page, "Users & Roles")).toBeVisible();
}

/**
 * The scope the role catalog grants `role` for `permission`, read off the
 * matrix. Returns null when the permission or the role is not in the catalog.
 *
 * "—" is the catalog saying no; every other value ("yes", "own", "all", …) is
 * a grant.
 */
export async function scopeInMatrix(
  page: Page,
  role: string,
  permission: string,
): Promise<string | null> {
  const headers = await page.getByRole("columnheader").allInnerTexts();
  const column = headers.findIndex((header) => header.trim().toLowerCase() === role.toLowerCase());
  if (column === -1) return null;

  const rows = page.getByRole("row");
  const total = await rows.count();
  for (let index = 0; index < total; index++) {
    const cells = rows.nth(index).getByRole("cell");
    if ((await cells.count()) === 0) continue; // the header row has no cells

    // The permission cell reads "agents:edit" or "agents:edit (scoped)".
    const name = (await cells.first().innerText()).trim();
    if (name === permission || name.startsWith(`${permission} `)) {
      return (await cells.nth(column).innerText()).trim();
    }
  }
  return null;
}
