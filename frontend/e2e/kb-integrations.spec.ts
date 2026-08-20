import type { APIRequestContext } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_AWS_SECRET_NAME, SEEDED_KB_NAME, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/** The integration this spec configures, and the copy it makes of it. */
const REUSABLE_NAME = "e2e-reusable-bucket";
const CLONE_NAME = `${REUSABLE_NAME} (${SEEDED_KB_NAME})`;

interface SyncSource {
  id: string;
  name: string;
  collection_name: string | null;
}

async function json<T>(request: APIRequestContext, url: string): Promise<T> {
  const response = await request.get(url);
  expect(response.ok(), `${url} answered ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

async function seededKbId(request: APIRequestContext): Promise<string> {
  const { items } = await json<{ items: { id: string; name: string }[] }>(request, "/api/kb");
  const kb = items.find((entry) => entry.name === SEEDED_KB_NAME);
  expect(kb, `the seed's knowledge base "${SEEDED_KB_NAME}" is missing`).toBeTruthy();
  return kb?.id ?? "";
}

async function activeOrgId(request: APIRequestContext): Promise<string> {
  const { items } = await json<{ items: { id: string }[] }>(request, "/api/orgs");
  return items[0]?.id ?? "";
}

/**
 * Configure a connector once, use it in a knowledge base.
 *
 * This is the journey that used to live on `/orgs/{id}/integrations` and now
 * lives on `/rag`, and it is worth a browser: an integration with no collection
 * can only be made through a wizard whose collection step is deliberately
 * absent, and cloning one is a Radix select that jsdom cannot open. Its
 * credentials are write-only — the API answers with `••••••` — so a copy that
 * did not go through the clone route could never be made to sync at all.
 */
test.describe("Reusable integrations", () => {
  test.afterEach(async ({ page }) => {
    // Through the API rather than the UI: a failed assertion mid-journey must
    // still leave the database as it was found, and the confirmation dialogs
    // are not what is under test.
    const orgId = await activeOrgId(page.request);
    const kbId = await seededKbId(page.request);

    const { items: kbSources } = await json<{ items: SyncSource[] }>(
      page.request,
      `/api/kb/${kbId}/sync-sources`,
    );
    for (const source of kbSources.filter((entry) => entry.name === CLONE_NAME)) {
      await page.request.delete(`/api/kb/${kbId}/sync-sources/${source.id}`);
    }

    const { items: orgSources } = await json<{ items: SyncSource[] }>(
      page.request,
      `/api/orgs/${orgId}/integrations`,
    );
    for (const source of orgSources.filter((entry) => entry.name === REUSABLE_NAME)) {
      await page.request.delete(`/api/orgs/${orgId}/integrations/${source.id}`);
    }
  });

  test("an integration configured on /rag can be used in a knowledge base", async ({ page }) => {
    await page.goto("/rag");
    await expect(pageHeading(page, "Knowledge bases")).toBeVisible();
    await expect(page.getByText(SEEDED_KB_NAME, { exact: true }).first()).toBeVisible();

    // Its own tab since #939, rather than a section under the base grid.
    await page.getByRole("tab", { name: "Integrations" }).click();
    await page.getByRole("button", { name: "Add integration" }).click();
    const wizard = page.getByRole("dialog");
    await wizard.getByLabel("Source name").fill(REUSABLE_NAME);
    await wizard.getByRole("button", { name: "S3 / MinIO" }).click();
    await wizard.getByRole("button", { name: "Continue" }).click();

    await wizard.getByLabel("Bucket Name").fill("e2e-bucket");
    await wizard.getByRole("button", { name: "Continue" }).click();

    // The credential is a vault secret this source references rather than two
    // fields it carries, so the step offers what the organization holds - and
    // only the `aws_credentials` one, which is what an S3 connector takes (#937).
    await wizard.getByLabel("Vault credential").click();
    await page.getByRole("option", { name: new RegExp(SEEDED_AWS_SECRET_NAME) }).click();
    await wizard.getByRole("button", { name: "Continue" }).click();

    // No collection step: an integration made here belongs to none, which is
    // the whole difference between this list and a knowledge base's own.
    await expect(wizard.getByText("Target collection")).toBeHidden();
    await wizard.getByRole("button", { name: "Create source" }).click();

    await expect(page.getByText(REUSABLE_NAME)).toBeVisible();

    await page.getByRole("button", { name: "Use in…" }).first().click();
    const clone = page.getByRole("dialog");
    await clone.getByRole("combobox", { name: "Knowledge base" }).click();
    await page.getByRole("option", { name: SEEDED_KB_NAME }).click();
    await clone.getByRole("button", { name: "Add to knowledge base" }).click();

    // The copy is the knowledge base's, and the original stays where it is —
    // the next collection needs it too.
    await expect(clone).toBeHidden();
    await expect(page.getByText(REUSABLE_NAME)).toBeVisible();

    const kbId = await seededKbId(page.request);
    // Straight to the section, which the URL can name since #939 - rather than
    // landing on the documents and clicking across.
    await page.goto(`/rag/${kbId}?tab=sync`);
    await expect(pageHeading(page, SEEDED_KB_NAME)).toBeVisible();
    await expect(page.getByText(CLONE_NAME)).toBeVisible();
  });
});
