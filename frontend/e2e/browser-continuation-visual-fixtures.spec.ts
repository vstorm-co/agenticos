import type { Page, Route } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE, FAKE_KEY_LABEL, OWNER_EMAIL, pageHeading } from "./helpers";
import {
  CONTINUATION_IDS as ids,
  browserContinuationFixture,
  continuationSourceFixture,
} from "../src/test-utils/browser-credential-continuation-fixtures";
import { browserEligibilityFixture } from "../src/test-utils/browser-credential-plan-fixtures";
import type { BrowserCredentialContinuation } from "../src/types/browser-credential-continuation";
import type { ToolApproval } from "../src/types/runs";

test.use({ storageState: AUTH_STATE });

/**
 * Fixture-only rendering of the real approval queue and continuation components.
 * The running stack supplies the seeded owner/session. Every continuation receipt
 * and write below is synthetic; no cookies are exported, no hosted controller or
 * external website is opened, and no model/provider request is made.
 */
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;
const SOURCE_PATH = "/api/runs/" + ids.run + "/browser-credential-plans/" + ids.child;
const CONTINUATION_PATH = SOURCE_PATH + "/continuation";
const CONFIRMATION_PATH = CONTINUATION_PATH + "/" + ids.continuation + "/confirmation";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const NAME = "Visual fixture: protected continuation";

async function seededOwner(page: Page): Promise<string> {
  await page.goto("/vault");
  await expect(pageHeading(page, "Vault")).toBeVisible();
  await expect(page.getByRole("main").getByText(FAKE_KEY_LABEL).first()).toBeVisible();
  const response = await page.request.get("/api/auth/me");
  expect(response.status()).toBe(200);
  const owner = (await response.json()) as { id: string; email: string };
  expect(owner.email).toBe(OWNER_EMAIL);
  expect(owner.id).toMatch(UUID);
  return owner.id;
}

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function contained(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    "the real continuation surface fits the current viewport",
  ).toBe(true);
}

test.describe("Protected continuation — fixture-only rendered evidence", () => {
  for (const size of SIZES) {
    for (const outcome of ["continued", "unknown"] as const) {
      test(
        "captures dedicated consent and " + outcome + " receipt at " + size.name + " width",
        async ({ page }, testInfo) => {
          await page.setViewportSize(size);
          const owner = await seededOwner(page);
          const source = continuationSourceFixture();
          const keep = outcome === "continued";
          let receipt: BrowserCredentialContinuation | null = null;
          let reads = 0;
          const writes: { path: string; body: unknown }[] = [];
          const approval: ToolApproval = {
            id: ids.continuation,
            run_id: ids.run,
            agent_id: ids.plan,
            agent_name: "Visual fixture assistant",
            tool_id: "browser_continue_credential_session",
            capability_tool_id: "browser_continue_credential_session",
            tool_args: { continuation_id: ids.continuation, source_submission_id: ids.child },
            subagent_name: null,
            subagent_agent_id: null,
            status: "pending",
            always_asks: true,
            content_hidden: false,
            decided_by_user_id: null,
            decided_at: null,
            decided_via: "click",
            note: null,
            created_at: new Date().toISOString(),
          };
          await page.route(/\/api\/approvals(?:\/[^?]*)?(?:\?.*)?$/, async (route) => {
            expect(route.request().method(), "generic approval cannot authorize this effect").toBe(
              "GET",
            );
            const url = new URL(route.request().url());
            expect(url.pathname).toBe("/api/approvals");
            const items = url.searchParams.has("status") || writes.length ? [] : [approval];
            await json(route, { items, total: items.length });
          });
          await page.route(
            new RegExp("/api/runs/" + ids.run + "(?:/[^?]*)?(?:\\?.*)?$"),
            async (route) => {
              const request = route.request();
              const url = new URL(request.url());
              const path = url.pathname;
              const organization = request.headers()["x-organization-id"];
              if (path === CONTINUATION_PATH || path === CONFIRMATION_PATH) {
                expect(organization, "receipt uses the current real organization").toMatch(UUID);
                if (!organization) throw new Error("The fixture requires an organization header");
              }
              if (request.method() === "GET") {
                if (path === SOURCE_PATH) return json(route, source);
                if (path === "/api/runs/" + ids.run + "/browser-credentials") {
                  expect(url.searchParams.get("call_id")).toBe(source.call_id);
                  expect(url.searchParams.get("tab_id")).toBe(source.tab_id);
                  return json(route, [{ ...browserEligibilityFixture(), name: NAME }]);
                }
                expect(path).toBe(CONTINUATION_PATH);
                if (!organization) throw new Error("The fixture requires an organization header");
                reads++;
                receipt ??= browserContinuationFixture({
                  user_id: owner,
                  organization_id: organization,
                });
                return json(route, receipt);
              }
              expect(request.method()).toBe("POST");
              expect(path, "only the dedicated exact continuation confirmation is allowed").toBe(
                CONFIRMATION_PATH,
              );
              expect(receipt?.state).toBe("awaiting_confirmation");
              if (!receipt) throw new Error("The receipt must be read before consent");
              const body: unknown = request.postDataJSON();
              expect(body).toEqual({
                document_id: ids.continuationDocument,
                authorization_generation: ids.generation,
                approve: true,
                keep_signed_in: keep,
              });
              writes.push({ path, body });
              receipt = {
                ...receipt,
                state: outcome,
                keep_signed_in: keep,
                saved_sign_in_id: keep ? ids.saved : null,
                continuation_call_id: keep ? ids.continuationCall : null,
                continuation_tab_id: keep ? ids.continuationTab : null,
                reason_code: keep ? null : "uncertain_continuation",
              };
              return json(route, receipt, 202);
            },
          );

          await page.goto("/runs?tab=approvals");
          const review = page.getByRole("button", { name: "Review continuation", exact: true });
          await expect(review).toBeVisible();
          await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
          await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
          expect(writes).toEqual([]);
          await contained(page);
          if (outcome === "continued") {
            await page.screenshot({
              path: testInfo.outputPath("continuation-queue-fixture-" + size.name + ".png"),
              animations: "disabled",
            });
          }
          await review.click();
          const dialog = page.getByRole("dialog");
          const panel = dialog.getByRole("region", {
            name: "Continue with protected cookies",
            exact: true,
          });
          await expect(panel.getByText(source.origin!, { exact: true })).toBeVisible();
          await expect(dialog.getByText(NAME, { exact: true })).toBeVisible();
          await expect(panel.getByText(/Both browser views remain protected/)).toBeVisible();
          await expect(
            panel.getByText(/Page text, images and ordinary browser controls stay hidden/),
          ).toBeVisible();
          await expect(panel.getByText(/up to seven days/)).toBeVisible();
          const checkbox = panel.getByRole("checkbox", { name: "Keep me signed in", exact: true });
          await expect(checkbox).not.toBeChecked();
          const confirm = panel.getByRole("button", {
            name: "Continue in protected browser",
            exact: true,
          });
          await expect(confirm).toBeEnabled();
          await expect(
            dialog.getByRole("button", { name: "Confirm fill", exact: true }),
          ).toHaveCount(0);
          await expect(
            dialog.getByRole("button", { name: "Submit this form", exact: true }),
          ).toHaveCount(0);
          expect(writes).toEqual([]);
          await contained(page);
          if (outcome === "continued") {
            await confirm.scrollIntoViewIfNeeded();
            await page.screenshot({
              path: testInfo.outputPath("continuation-consent-fixture-" + size.name + ".png"),
              animations: "disabled",
            });
          }
          if (keep) await checkbox.check();

          await confirm.click();
          await expect(
            panel.getByText(
              keep ? "Protected continuation established" : "Continuation outcome unknown",
              { exact: true },
            ),
          ).toBeVisible();
          expect(writes).toHaveLength(1);
          await expect(panel.getByRole("checkbox")).toHaveCount(0);
          await expect(
            panel.getByRole("button", { name: "Prepare continuation", exact: true }),
          ).toHaveCount(0);
          await expect(
            panel.getByRole("button", { name: "Retry the same decision", exact: true }),
          ).toHaveCount(0);
          if (keep) {
            await expect(panel.getByText(/does not prove that sign-in succeeded/)).toBeVisible();
            await expect(panel.getByText(/saved with your explicit consent/)).toBeVisible();
            await expect(
              panel.getByRole("link", { name: "Open protected view", exact: true }),
            ).toHaveAttribute("href", "/browse/" + ids.run + "/" + ids.continuationCall);
            await expect(
              panel.getByRole("link", { name: "Manage saved sign-ins", exact: true }),
            ).toHaveAttribute("href", "/settings/sign-ins");
          } else {
            await expect(panel.getByText(/cannot be repeated/)).toBeVisible();
            await expect(
              panel.getByRole("link", { name: "Open protected view", exact: true }),
            ).toHaveCount(0);
            const before = reads;
            await panel.getByRole("button", { name: "Check continuation", exact: true }).click();
            await expect.poll(() => reads).toBeGreaterThan(before);
            expect(writes).toHaveLength(1);
          }
          await contained(page);
          await panel.scrollIntoViewIfNeeded();
          await page.screenshot({
            path: testInfo.outputPath(
              "continuation-" + outcome + "-receipt-fixture-" + size.name + ".png",
            ),
            animations: "disabled",
          });
        },
      );
    }
  }
});
