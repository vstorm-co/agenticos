import type { Page, Route, WebSocketRoute } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE, FAKE_KEY_LABEL, OWNER_EMAIL, pageHeading } from "./helpers";
import { BROWSER_IDS as ids } from "../src/test-utils/browser-credential-fixtures";
import {
  browserEligibilityFixture,
  browserPlanFixture,
  browserSubmissionFixture,
} from "../src/test-utils/browser-credential-plan-fixtures";
import type { BrowserCredentialPlan } from "../src/types/browser-credentials";
import type { Secret } from "../src/types/secrets";
import type { ToolApproval } from "../src/types/runs";

test.use({ storageState: AUTH_STATE });

/**
 * Fixture-only rendering evidence on the real product routes. The seed and
 * catalog are read from the running stack. Saved metadata, plan receipts and
 * the addressed socket are synthetic; no credential is stored or sent to a
 * site, no controller is started, and no model is called.
 */
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;
const LOGIN_NAME = "Visual fixture: browser login";
const ORIGIN = "https://accounts.example";
const PLAN_PATH = "/api/runs/" + ids.run + "/browser-credential-plans/" + ids.plan;
const CALL = "browser-call";

async function seededOwner(page: Page): Promise<{ id: string; email: string }> {
  await page.goto("/vault");
  await expect(pageHeading(page, "Vault")).toBeVisible();
  await expect(page.getByRole("main").getByText(FAKE_KEY_LABEL).first()).toBeVisible();
  const response = await page.request.get("/api/auth/me");
  expect(response.status(), "the real owner session answered").toBe(200);
  const owner = (await response.json()) as { id: string; email: string };
  expect(owner.email).toBe(OWNER_EMAIL);
  expect(owner.id).toMatch(/^[0-9a-f-]{36}$/i);
  return owner;
}

async function contained(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    "the actual product surface fits the viewport",
  ).toBe(true);
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function eligible() {
  return { ...browserEligibilityFixture(), name: LOGIN_NAME };
}

async function installPlanReads(
  page: Page,
  read: () => BrowserCredentialPlan,
  readChild: () => BrowserCredentialPlan | null,
  write?: (route: Route, path: string) => Promise<void>,
) {
  await page.route(
    new RegExp("/api/runs/" + ids.run + "/browser-credentials(?:\\?.*)?$"),
    async (route) => {
      expect(route.request().method()).toBe("GET");
      expect(new URL(route.request().url()).searchParams.get("call_id")).toBe(CALL);
      expect(new URL(route.request().url()).searchParams.get("tab_id")).toBe("main");
      await json(route, [eligible()]);
    },
  );
  await page.route(new RegExp(PLAN_PATH + "(?:/[^?]*)?(?:\\?.*)?$"), async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") {
      if (write) return write(route, path);
      throw new Error("A read-only visual fixture attempted credential consent");
    }
    if (path === PLAN_PATH) return json(route, read());
    if (path === PLAN_PATH + "/submission") return json(route, readChild());
    throw new Error("An unexpected credential receipt was requested");
  });
}

test.describe("Browser credentials — fixture-only visual evidence", () => {
  for (const size of SIZES) {
    test(
      "captures loaded Vault metadata, owner policy and typed login at " + size.name + " width",
      async ({ page }, testInfo) => {
        await page.setViewportSize(size);
        const owner = await seededOwner(page);
        const kindsResponse = await page.request.get("/api/secrets/kinds");
        expect(kindsResponse.status()).toBe(200);
        const kinds = (await kindsResponse.json()) as { items: { kind: string }[] };
        expect(kinds.items.map((kind) => kind.kind)).toEqual(
          expect.arrayContaining(["browser_login", "browser_profile"]),
        );

        const secret: Secret = {
          id: ids.secret,
          name: LOGIN_NAME,
          description: "Synthetic metadata only",
          kind: "browser_login",
          hint: "NEVER-RENDER-FIXTURE-HINT",
          purpose: "custom",
          usage_scope: "organization",
          visibility: "private",
          owner_user_id: owner.id,
          can_edit: true,
          browser: {
            allowed_origins: [ORIGIN],
            available_fields: ["username", "password", "totp"],
            has_totp: true,
          },
        };
        await page.route(/\/api\/secrets(?:\?.*)?$/, async (route) => {
          expect(route.request().method(), "this capture never creates or replaces a secret").toBe(
            "GET",
          );
          await json(route, { items: [secret], total: 1 });
        });
        await page.route("**/api/secrets/" + ids.secret + "/browser-policy", (route) =>
          json(route, {
            secret_id: ids.secret,
            authorization_generation: ids.generation,
            mode: "shared",
            agent_ids: [ids.child],
            member_ids: [owner.id],
          }),
        );
        await page.route(/\/api\/agents(?:\?.*)?$/, (route) =>
          json(route, {
            items: [
              {
                id: ids.child,
                name: "Visual fixture browser assistant",
                status: "draft",
                can_run: true,
              },
            ],
            total: 1,
          }),
        );
        await page.route(/\/api\/orgs\/[^/]+\/members(?:\?.*)?$/, (route) =>
          json(route, {
            items: [
              {
                user_id: owner.id,
                full_name: "Visual fixture teammate",
                email: "fixture@example.invalid",
              },
            ],
            total: 1,
          }),
        );

        await page.reload();
        await expect(page.getByText(LOGIN_NAME, { exact: true }).first()).toBeVisible();
        await expect(page.getByText("NEVER-RENDER-FIXTURE-HINT")).toHaveCount(0);
        await contained(page);
        await page.screenshot({
          path: testInfo.outputPath("browser-vault-metadata-fixture-" + size.name + ".png"),
        });

        await page.getByRole("button", { name: "Manage browser use for " + LOGIN_NAME }).click();
        const policy = page.getByRole("dialog");
        await expect(policy.getByText(ORIGIN, { exact: true })).toBeVisible();
        await expect(
          policy.getByRole("checkbox", { name: "Visual fixture browser assistant" }),
        ).toBeChecked();
        await expect(
          policy.getByRole("checkbox", { name: "Visual fixture teammate" }),
        ).toBeChecked();
        await expect(policy.getByRole("button", { name: "Save browser use" })).toBeEnabled();
        await contained(page);
        await page.screenshot({
          path: testInfo.outputPath("browser-owner-policy-fixture-" + size.name + ".png"),
        });
        await page.keyboard.press("Escape");

        await page.getByRole("button", { name: "Add browser credential", exact: true }).click();
        await page.getByRole("menuitem", { name: "Add browser login", exact: true }).click();
        const login = page.getByRole("dialog");
        await login.getByLabel("Name", { exact: true }).fill("Visual fixture: unsaved login");
        await login.getByLabel("Allowed origins", { exact: true }).fill(ORIGIN);
        await login.getByLabel("Username", { exact: true }).fill("fixture-identifier");
        await login.getByLabel("Password", { exact: true }).fill("fixture-password-only");
        await expect(login.getByLabel("Username", { exact: true })).toHaveAttribute(
          "type",
          "password",
        );
        await expect(login.getByLabel("Password", { exact: true })).toHaveAttribute(
          "type",
          "password",
        );
        await contained(page);
        await page.screenshot({
          path: testInfo.outputPath("browser-login-form-fixture-" + size.name + ".png"),
        });
        await login.getByRole("checkbox", { name: "Include a verification code (TOTP)" }).check();
        await login.getByLabel("Verification code seed", { exact: true }).fill("JBSWY3DPEHPK3PXP");
        await expect(login.getByLabel("Verification code seed", { exact: true })).toHaveAttribute(
          "type",
          "password",
        );
        await login.getByLabel("Verification code seed", { exact: true }).scrollIntoViewIfNeeded();
        await page.screenshot({
          path: testInfo.outputPath("browser-totp-form-fixture-" + size.name + ".png"),
        });
      },
    );

    test(
      "captures exact review and separate submission receipts at " + size.name + " width",
      async ({ page }, testInfo) => {
        await page.setViewportSize(size);
        await seededOwner(page);
        let parent = browserPlanFixture();
        let child: BrowserCredentialPlan | null = null;
        const writes: string[] = [];
        const approval: ToolApproval = {
          id: ids.plan,
          run_id: ids.run,
          agent_id: ids.child,
          agent_name: "Visual fixture assistant",
          tool_id: "browser_fill_credential",
          capability_tool_id: "browser_fill_credential",
          tool_args: { plan_id: ids.plan },
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
        await page.route(/\/api\/approvals(?:\?.*)?$/, (route) => {
          // The pending endpoint only takes pagination; history has its own route.
          const items = parent.state === "awaiting_confirmation" ? [approval] : [];
          return json(route, { items, total: items.length });
        });
        await installPlanReads(
          page,
          () => parent,
          () => child,
          async (route, path) => {
            writes.push(path);
            const body = route.request().postDataJSON();
            if (path === PLAN_PATH + "/confirmation") {
              expect(body).toEqual({
                document_id: ids.document,
                authorization_generation: ids.generation,
                approve: true,
              });
              parent = {
                ...parent,
                state: "filled",
                output_protected: true,
                submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
              };
              return json(route, parent);
            }
            expect(path).toBe(PLAN_PATH + "/submission");
            expect(body).toEqual({
              request_id: expect.stringMatching(/^[0-9a-f-]{36}$/i),
              document_id: ids.document,
              authorization_generation: ids.generation,
            });
            child = browserSubmissionFixture(parent, {
              id: body.request_id as string,
              state: "unknown",
              reason_code: "uncertain_fill_effect",
            });
            return json(route, child, 202);
          },
        );

        await page.goto("/runs?tab=approvals");
        await page.getByRole("button", { name: "Review destination", exact: true }).click();
        const dialog = page.getByRole("dialog");
        await expect(dialog.getByText(ORIGIN, { exact: true })).toBeVisible();
        await expect(dialog.getByText(LOGIN_NAME, { exact: true })).toBeVisible();
        await expect(dialog.getByText("Username", { exact: true })).toBeVisible();
        await expect(dialog.getByText("Password", { exact: true })).toBeVisible();
        await expect(
          dialog.getByRole("button", { name: "Confirm fill", exact: true }),
        ).toBeEnabled();
        await expect(dialog.locator("time")).toHaveAttribute("datetime", parent.expires_at);
        expect(writes).toEqual([]);
        await contained(page);
        await page.screenshot({
          path: testInfo.outputPath("browser-destination-review-fixture-" + size.name + ".png"),
        });

        await dialog.getByRole("button", { name: "Confirm fill", exact: true }).click();
        const submit = dialog.getByRole("button", { name: "Submit this form", exact: true });
        await expect(submit).toBeEnabled();
        await expect(dialog.getByText("Selected fields filled", { exact: true })).toBeVisible();
        expect(writes).toEqual([PLAN_PATH + "/confirmation"]);
        await submit.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: testInfo.outputPath("browser-separate-submit-fixture-" + size.name + ".png"),
        });
        await submit.click();
        await expect(dialog.getByText("Outcome unknown", { exact: true })).toBeVisible();
        await expect(dialog.getByText(/already has its one submission attempt/)).toBeVisible();
        await expect(
          dialog.getByRole("button", { name: "Submit this form", exact: true }),
        ).toHaveCount(0);
        expect(writes).toEqual([PLAN_PATH + "/confirmation", PLAN_PATH + "/submission"]);
        await page.screenshot({
          path: testInfo.outputPath("browser-unknown-receipt-fixture-" + size.name + ".png"),
        });
      },
    );

    test(
      "captures the protected live view and manual handoff at " + size.name + " width",
      async ({ page }, testInfo) => {
        await page.setViewportSize(size);
        await seededOwner(page);
        const parent = browserPlanFixture({
          state: "filled",
          output_protected: true,
          submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
        });
        const child = browserSubmissionFixture(parent, {
          state: "unknown",
          reason_code: "uncertain_fill_effect",
        });
        await installPlanReads(
          page,
          () => parent,
          () => child,
        );
        let socket: WebSocketRoute | null = null;
        const commands: string[] = [];
        await page.routeWebSocket(new RegExp("/api/v1/ws/browse/" + ids.run + "/" + CALL), (ws) => {
          socket = ws;
          ws.onMessage((message) => commands.push(String(message)));
          ws.send(
            JSON.stringify({
              type: "browser_snapshot",
              task: "RAW_FIXTURE_ONLY_TASK",
              can_control: true,
              can_remember: true,
              trace: [
                {
                  kind: "browser_protected",
                  output_protected: true,
                  run_id: ids.run,
                  call_id: CALL,
                  tab_id: "main",
                  step: 2,
                  credential_plan_id: ids.plan,
                  credential_operation: "fill",
                },
              ],
              frame: {
                kind: "browser_frame",
                run_id: ids.run,
                call_id: CALL,
                tab_id: "main",
                step: 1,
                image: "data:image/jpeg;base64,UkFX",
                title: "RAW_FIXTURE_ONLY_TITLE",
                url: ORIGIN + "/private?raw=1",
              },
            }),
          );
        });

        await page.goto("/browse/" + ids.run + "/" + CALL);
        const main = page.getByRole("main");
        // The page title and the window bar both name the protected state.
        await expect(
          main.getByRole("heading", { name: "Protected browser", exact: true, level: 1 }),
        ).toBeVisible();
        await expect(
          main.getByRole("heading", { name: "Protected browser", exact: true, level: 2 }),
        ).toBeVisible();
        const liveTitle = main.getByRole("heading", { name: "Live browser", exact: true });
        await expect(liveTitle).toHaveCount(0);
        await expect(
          main.getByText(
            "Page text, images and ordinary browser controls stay hidden. Saved values may be present.",
            { exact: true },
          ),
        ).toBeVisible();
        await expect(main.getByText(ORIGIN, { exact: true })).toBeVisible();
        await expect(main.getByText(LOGIN_NAME, { exact: true })).toBeVisible();
        await expect(main.getByText("Outcome unknown", { exact: true })).toBeVisible();
        await expect(main.getByRole("img")).toHaveCount(0);
        await expect(main.getByRole("application")).toHaveCount(0);
        await expect(main.getByRole("textbox")).toHaveCount(0);
        await expect(main.getByText(/RAW_FIXTURE_ONLY/)).toHaveCount(0);
        expect(socket).not.toBeNull();
        (socket as unknown as WebSocketRoute).send(
          JSON.stringify({
            kind: "browser_opened",
            output_protected: false,
            run_id: ids.run,
            call_id: CALL,
            tab_id: "main",
            step: 3,
            title: "RAW_FIXTURE_ONLY_LATE",
            url: ORIGIN + "/private",
            navigable: true,
          }),
        );
        const handoff = main.getByRole("link", { name: "Open this site", exact: true });
        await expect(handoff).toHaveAttribute("href", ORIGIN);
        await expect(main.getByText(/use Stop in the chat where it is running/)).toBeVisible();
        await expect(
          main.getByText(/Hosted sign-in and cookies are not transferred/),
        ).toBeVisible();
        await expect(main.getByText(/RAW_FIXTURE_ONLY/)).toHaveCount(0);
        expect(commands).toEqual([]);
        await contained(page);
        await page.screenshot({
          path: testInfo.outputPath("browser-protected-view-fixture-" + size.name + ".png"),
        });
        await handoff.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: testInfo.outputPath("browser-manual-handoff-fixture-" + size.name + ".png"),
        });
      },
    );
  }
});
