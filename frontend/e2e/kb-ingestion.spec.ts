import type { APIRequestContext, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_KB_NAME, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/** The collection this spec makes, parsed with something other than the default. */
const KB_NAME = "E2E Parser Choice";
/** Not the deployment default, and the only parser that reveals a tier control. */
const PARSER = "LlamaParse";
const CHUNK_SIZE = "1024";

interface KBRow {
  id: string;
  name: string;
}

/**
 * Remove any collection this spec left behind, so it starts from nothing.
 *
 * On entry rather than on exit, which is the convention here: a run that fails
 * halfway has to be followed by a run that still works, and an `afterEach` does
 * not survive a crashed worker.
 */
async function clearPrevious(request: APIRequestContext): Promise<void> {
  const response = await request.get("/api/kb");
  expect(response.ok(), `/api/kb answered ${response.status()}`).toBe(true);
  const { items } = (await response.json()) as { items: KBRow[] };
  for (const kb of items.filter((entry) => entry.name === KB_NAME)) {
    await request.delete(`/api/kb/${kb.id}`);
  }
}

/**
 * Open the collection named `name` from the list.
 *
 * By the link's accessible name, because the card's link carries no text of its
 * own: it is an empty overlay stretched across the card, and the name is printed
 * by a sibling. A `hasText` filter over the anchors matches nothing at all.
 */
async function openCollection(page: Page, name: string): Promise<void> {
  await page.goto("/rag");
  await expect(pageHeading(page, "Knowledge bases")).toBeVisible();
  const card = page.getByRole("link", { name: `Open ${name}` });
  await expect(card).toBeVisible();
  await card.click();
  await expect(pageHeading(page, name)).toBeVisible();
}

/**
 * The panel that states what reads this collection's documents.
 *
 * Behind its own tab since #939 - the three sections used to stack - so reaching
 * it means choosing it. Idempotent: clicking a selected tab changes nothing, so
 * a spec that opens the panel twice is fine.
 */
async function howItReads(page: Page) {
  await page.getByRole("tab", { name: "How documents are read" }).click();
  return page.getByRole("region", { name: "How documents are read" });
}

/**
 * Choosing how a collection reads its documents, and being able to find out
 * later.
 *
 * The whole point of the feature is that both halves hold: a parser chosen in a
 * dialog has to survive the round trip, and somebody who did not choose it has
 * to be able to see what did. A spec that only asserted the form accepted a
 * click would pass against a backend that dropped the field on the floor.
 */
test.describe("Ingestion settings", () => {
  test("a collection keeps the parser it was created with, and says so", async ({ page }) => {
    await clearPrevious(page.request);

    await page.goto("/rag");
    await expect(pageHeading(page, "Knowledge bases")).toBeVisible();
    // The seed's collection, so a passing spec cannot be one run against a list
    // that failed to load — an empty list and a refused request look the same.
    await expect(page.getByText(SEEDED_KB_NAME, { exact: true }).first()).toBeVisible();

    await page.getByRole("button", { name: "New knowledge base" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill(KB_NAME);

    // Folded away until asked for: creating a collection is a two-field job.
    await expect(dialog.getByLabel("PDF parser")).toBeHidden();
    await dialog.getByText("How documents are parsed").click();

    await dialog.getByRole("combobox", { name: "PDF parser" }).click();
    await page.getByRole("option", { name: PARSER, exact: true }).click();

    // The tier belongs to this parser alone, so its appearance is the form
    // saying it understood the choice rather than merely recording a click.
    await expect(dialog.getByLabel("LlamaParse tier")).toBeVisible();

    await dialog.getByLabel("Chunk size").fill(CHUNK_SIZE);
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(dialog).toBeHidden();

    await openCollection(page, KB_NAME);
    await expect(await howItReads(page)).toContainText(PARSER);
    await expect(await howItReads(page)).toContainText("1,024 characters");

    // Through the server, not through the state the dialog left behind. This is
    // the assertion the whole spec exists for: everything above would also pass
    // if `ingestion_config` were dropped on the way out.
    await page.reload();
    await expect(pageHeading(page, KB_NAME)).toBeVisible();
    await expect(await howItReads(page)).toContainText(PARSER);
    await expect(await howItReads(page)).toContainText("1,024 characters");

    // And it can be changed afterwards. The API replaces the object wholesale,
    // so this is also the only assertion that the dialog sent the nine fields
    // nobody touched alongside the one that was.
    // Scoped to this panel: the page also carries a Reranking section with its
    // own Edit, so a page-wide "Edit" is now two buttons.
    await howItReads(page).getByRole("button", { name: "Edit" }).click();
    const settings = page.getByRole("dialog");
    await settings.getByLabel("Chunk size").fill("2048");
    await settings.getByRole("button", { name: "Save" }).click();
    await expect(settings).toBeHidden();

    await page.reload();
    await expect(await howItReads(page)).toContainText("2,048 characters");
    await expect(await howItReads(page)).toContainText(PARSER);
  });

  test("the embedding model is stated as a fact and offered as no control", async ({ page }) => {
    // It is recorded once when the collection is made and cannot be changed:
    // the store writes `embedding vector(N)` at creation, and two models of the
    // same width write into different spaces that search goes on comparing. A
    // dropdown here would be an invitation to break a collection silently.
    await openCollection(page, SEEDED_KB_NAME);

    const embeddings = (await howItReads(page)).getByText("dimensions");
    await expect(embeddings).toBeVisible();
    await expect(
      (await howItReads(page)).getByRole("combobox", { name: /embedding/i }),
    ).toHaveCount(0);
  });

  test("a per-upload override says it is not changing the collection", async ({ page }) => {
    await openCollection(page, SEEDED_KB_NAME);
    const before = await (await howItReads(page)).innerText();

    await page.getByRole("button", { name: "Parse options" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Chunk size").fill("2048");
    await dialog.getByRole("button", { name: "Apply 1 change" }).click();
    await expect(dialog).toBeHidden();

    // Two claims, and the second is the one that matters: the departure applies
    // to documents, and the collection is exactly as it was.
    await expect(page.getByText("The collection itself is unchanged.")).toBeVisible();
    expect(await (await howItReads(page)).innerText()).toBe(before);

    // And it can be put back, which is what stops it applying to whatever is
    // dropped on this page twenty minutes from now.
    await page.getByRole("button", { name: "Clear" }).click();
    await expect(page.getByText("The collection itself is unchanged.")).toBeHidden();
  });

  /**
   * What parsed one document, read off the document.
   *
   * Skipped, and not because the assertion is uncertain: nothing in this
   * environment can ingest a file at all. `docker-compose.yml` runs
   * `postgres:16-alpine`, which has no pgvector, so the first upload into any
   * collection fails inside `create_collection` with
   * `extension "vector" is not available` — a 500 before a document row is ever
   * committed. The suite's own `apiFailures` fixture already records that RAG is
   * out of reach here ("RAG needs an embedding provider, which a test deployment
   * has no key for").
   *
   * Unskip it once the compose file runs a pgvector image and the deployment has
   * an embedding key. The assertions below are the ones that matter: a document
   * records the parser that read it, and an overridden one is marked as such —
   * which is how "why did this one come out differently" gets answered months
   * later, when the collection's settings have moved on.
   */
  test.skip("a document records what parsed it", async ({ page }) => {
    await openCollection(page, SEEDED_KB_NAME);

    await page.getByRole("button", { name: "Parse options" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Chunk size").fill("2048");
    await dialog.getByRole("button", { name: "Apply 1 change" }).click();

    await page.locator('input[type="file"]').setInputFiles({
      name: "e2e-provenance.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("A short document, so the assertion is about the record, not the text."),
    });

    const row = page.getByRole("row").filter({ hasText: "e2e-provenance.txt" });
    await expect(row).toBeVisible();
    // The parser stored on the document, not the one the collection is set to.
    await expect(row).toContainText("pymupdf");
    await expect(row).toContainText("overridden");
  });
});
