import type { Page, Route, WebSocketRoute } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE, OWNER_EMAIL, pageHeading } from "./helpers";
import {
  BROWSER_PROCEDURE_TEACHING_IDS as ids,
  browserProcedureTeachingFixture,
  browserProcedureTeachingReviewFixture,
  browserProcedureTeachingSummaryFixture,
} from "../src/test-utils/browser-procedure-teaching";
import type {
  BrowserProcedureTeaching,
  BrowserProcedureTeachingStart,
} from "../src/types/browser-procedure-teaching";

test.use({ storageState: AUTH_STATE });
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;
const CALL = "teaching-call";
const ORIGIN = "https://reports.example";
async function json(route: Route, body: unknown) {
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
}
async function seed(page: Page) {
  const request = page.waitForRequest(
    (value) => new URL(value.url()).pathname === "/api/skills" && value.method() === "GET",
  );
  await page.goto("/skills");
  await expect(pageHeading(page, "Skills")).toBeVisible();
  const organization = (await request).headers()["x-organization-id"];
  expect(organization).toMatch(/^[0-9a-f-]{36}$/i);
  if (!organization) throw new Error("The authenticated Skills request omitted its organization");
  const response = await page.request.get("/api/auth/me");
  expect(response.status()).toBe(200);
  const owner = (await response.json()) as { id: string; email: string };
  expect(owner.email).toBe(OWNER_EMAIL);
  const nativePolicy = await page.request.get("/api/browser-teaching-policy", {
    headers: { "X-Organization-Id": organization },
  });
  expect(
    nativePolicy.status(),
    "the real stack provides the teaching contract before fixtures",
  ).toBe(200);
  const nativeList = await page.request.get("/api/browser-procedures/teachings?limit=1", {
    headers: { "X-Organization-Id": organization },
  });
  expect(nativeList.status(), "owner discovery is implemented on this source").toBe(200);
  const list = (await nativeList.json()) as { items: unknown[]; next_cursor: unknown };
  expect(Array.isArray(list.items)).toBe(true);
  expect(list.next_cursor === null || typeof list.next_cursor === "string").toBe(true);
  return { owner, organization };
}
async function contained(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    "real page controls fit the viewport",
  ).toBe(true);
}
async function readPreference(page: Page) {
  await page.route("**/api/agents/" + ids.agent + "/browser-teaching-preference", async (route) => {
    expect(route.request().method()).toBe("GET");
    await json(route, { agent_id: ids.agent, enabled: false, generation: null, allowed: true });
  });
}

/**
 * Fixture-only visual evidence on actual product routes. Real owner auth and
 * native read contracts are checked first. Capture metadata, decisions and the
 * addressed socket are synthetic: no browser/controller, model job, provider
 * call, skill publication, or organization setting is started or changed.
 */
test.describe("Browser teaching — fixture-only visual evidence", () => {
  for (const size of SIZES) {
    test(
      "renders owner discovery, complete review and pending proposal at " + size.name + " width",
      async ({ page }, info) => {
        await page.setViewportSize(size);
        await seed(page);
        let session: BrowserProcedureTeaching = browserProcedureTeachingFixture({
          review: browserProcedureTeachingReviewFixture(),
        });
        const writes: unknown[] = [];
        await readPreference(page);
        await page.route(
          /\/api\/browser-procedures\/teachings(?:\/[^?]+)?(?:\?.*)?$/,
          async (route) => {
            const path = new URL(route.request().url()).pathname;
            if (route.request().method() === "GET") {
              if (path === "/api/browser-procedures/teachings")
                return json(route, {
                  items: [
                    browserProcedureTeachingSummaryFixture(session),
                    browserProcedureTeachingSummaryFixture({
                      id: ids.other,
                      title: "Visual fixture: completed-work suggestion",
                      source: "refinement",
                      verified_success: true,
                    }),
                  ],
                  next_cursor: null,
                });
              expect(path).toBe("/api/browser-procedures/teachings/" + ids.session);
              return json(route, session);
            }
            expect(route.request().method()).toBe("POST");
            expect(path).toBe("/api/browser-procedures/teachings/" + ids.session + "/propose");
            expect(route.request().headers()["if-match"]).toBe('"' + session.revision + '"');
            const body = route.request().postDataJSON();
            expect(body).toEqual({ mode: "reviewed" });
            writes.push(body);
            session = {
              ...session,
              status: "proposed",
              generation_state: "succeeded",
              generation_mode: "reviewed",
              proposal_id: ids.proposal,
              revision: session.revision + 1,
            };
            await json(route, session);
          },
        );
        await page.goto("/skills/teaching");
        await expect(
          page.getByRole("heading", { name: "Monthly report demonstration", exact: true }),
        ).toBeVisible();
        await expect(
          page.getByText("Visual fixture: completed-work suggestion", { exact: true }),
        ).toBeVisible();
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-list-fixture-" + size.name + ".png"),
        });
        await page.getByRole("link", { name: "Open capture", exact: true }).first().click();
        await expect(page.getByLabel("Skill name", { exact: true })).toHaveValue("monthly-report");
        await expect(page.getByLabel("Step 1 path template", { exact: true })).toHaveValue(
          "/reports",
        );
        await expect(page.getByLabel("Step 2 parameter name", { exact: true })).toHaveValue(
          "month",
        );
        await expect(
          page.getByRole("radio", { name: "Use my reviewed steps — no model call", exact: true }),
        ).toBeChecked();
        await expect(
          page.getByText(/human demonstration.*not been independently verified/),
        ).toBeVisible();
        expect(writes).toEqual([]);
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-review-fixture-" + size.name + ".png"),
          fullPage: true,
        });
        await page
          .getByRole("button", { name: "Create draft from reviewed steps", exact: true })
          .click();
        await expect(page.getByText("Skill draft ready for review", { exact: true })).toBeVisible();
        await expect(
          page.getByRole("link", { name: "Review proposals in Skills", exact: true }),
        ).toHaveAttribute("href", "/en/skills");
        expect(writes).toEqual([{ mode: "reviewed" }]);
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-proposal-fixture-" + size.name + ".png"),
        });
      },
    );

    test(
      "renders live consent and removes teaching after credential protection at " +
        size.name +
        " width",
      async ({ page }, info) => {
        await page.setViewportSize(size);
        const { owner } = await seed(page);
        let session: BrowserProcedureTeaching | null = null;
        let socket: WebSocketRoute | null = null;
        const writes: BrowserProcedureTeachingStart[] = [];
        await readPreference(page);
        await page.route("**/api/browser-teaching-policy", (route) =>
          json(route, { enabled: true, generation: ids.other, deployment_enabled: true }),
        );
        await page.route("**/api/runs/" + ids.run, (route) =>
          json(route, { id: ids.run, agent_id: ids.agent }),
        );
        await page.route(/\/api\/skills(?:\?.*)?$/, (route) =>
          json(route, { items: [], total: 0 }),
        );
        await page.route(
          /\/api\/browser-procedures\/teachings(?:\/[^?]+)?(?:\?.*)?$/,
          async (route) => {
            const path = new URL(route.request().url()).pathname;
            if (route.request().method() === "GET") {
              expect(session).not.toBeNull();
              expect(path).toBe("/api/browser-procedures/teachings/" + session!.id);
              return json(route, session);
            }
            expect(path).toBe("/api/browser-procedures/teachings");
            expect(route.request().method()).toBe("POST");
            const body = route.request().postDataJSON() as BrowserProcedureTeachingStart;
            expect(body).toMatchObject({
              run_id: ids.run,
              call_id: CALL,
              tab_id: "main",
              takeover_id: ids.takeover,
              allowed_origins: [ORIGIN],
            });
            expect(body).not.toHaveProperty("control_connection_id");
            writes.push(body);
            session = browserProcedureTeachingFixture({
              id: body.request_id,
              status: "recording",
              revision: 1,
              title: body.title,
              events: [],
            });
            await json(route, session);
          },
        );
        await page.routeWebSocket(new RegExp("/api/v1/ws/browse/" + ids.run + "/" + CALL), (ws) => {
          socket = ws;
          ws.send(
            JSON.stringify({
              type: "browser_snapshot",
              task: "Fixture-only demonstration",
              can_control: true,
              can_remember: false,
              trace: [
                {
                  kind: "browser_opened",
                  run_id: ids.run,
                  call_id: CALL,
                  tab_id: "main",
                  step: 0,
                  goal: "Fixture-only demonstration",
                  url: ORIGIN + "/reports",
                  title: "Synthetic reports",
                  navigable: true,
                },
                {
                  kind: "browser_held",
                  run_id: ids.run,
                  call_id: CALL,
                  tab_id: "main",
                  step: 0,
                  by: "Visual fixture owner",
                  by_user_id: owner.id,
                  takeover_id: ids.takeover,
                },
              ],
              frame: null,
            }),
          );
        });
        await page.goto("/browse/" + ids.run + "/" + CALL);
        await page.getByRole("button", { name: "Teach a browser procedure", exact: true }).click();
        const dialog = page.getByRole("dialog");
        await dialog
          .getByLabel("Demonstration title", { exact: true })
          .fill("Visual fixture: monthly report");
        await expect(
          dialog.getByRole("button", { name: "Start recording", exact: true }),
        ).toBeEnabled();
        await expect(
          dialog.getByText(/clicks and navigation affect the live website/),
        ).toBeVisible();
        await expect(
          dialog.getByRole("switch", {
            name: "Suggest procedures from my completed work",
            exact: true,
          }),
        ).not.toBeChecked();
        expect(writes).toEqual([]);
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-start-fixture-" + size.name + ".png"),
        });
        await dialog.getByRole("button", { name: "Start recording", exact: true }).click();
        await expect(
          dialog.getByRole("button", { name: "Pause recording", exact: true }),
        ).toBeVisible();
        await page.screenshot({
          path: info.outputPath("browser-teaching-recording-fixture-" + size.name + ".png"),
        });
        expect(writes).toHaveLength(1);
        expect(socket).not.toBeNull();
        (socket as unknown as WebSocketRoute).send(
          JSON.stringify({
            kind: "browser_protected",
            output_protected: true,
            run_id: ids.run,
            call_id: CALL,
            tab_id: "main",
            step: 1,
          }),
        );
        await expect(
          page.getByRole("heading", { name: "Protected browser", exact: true, level: 1 }),
        ).toBeVisible();
        (socket as unknown as WebSocketRoute).send(
          JSON.stringify({
            kind: "browser_held",
            output_protected: false,
            run_id: ids.run,
            call_id: CALL,
            tab_id: "main",
            step: 2,
            by_user_id: owner.id,
            takeover_id: ids.other,
          }),
        );
        await expect(
          page.getByRole("button", { name: "Teach a browser procedure", exact: true }),
        ).toHaveCount(0);
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await expect(page.getByRole("main").getByRole("application")).toHaveCount(0);
        expect(writes).toHaveLength(1);
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-protected-fixture-" + size.name + ".png"),
        });
      },
    );

    test(
      "renders the default-off organization control at " + size.name + " width",
      async ({ page }, info) => {
        await page.setViewportSize(size);
        const { organization } = await seed(page);
        await page.route("**/api/browser-teaching-policy", async (route) => {
          expect(route.request().method(), "this fixture does not change organization policy").toBe(
            "GET",
          );
          await json(route, { enabled: false, generation: null, deployment_enabled: true });
        });
        await page.goto("/orgs/" + organization + "/members");
        await page.locator('[data-tour="org-tab-governance"]').click();
        const section = page.locator('[data-tour="org-browser-teaching"]');
        await expect(
          section.getByRole("switch", { name: "Allow browser teaching", exact: true }),
        ).not.toBeChecked();
        await expect(section.getByText(/Off by default/)).toBeVisible();
        await section.scrollIntoViewIfNeeded();
        await contained(page);
        await page.screenshot({
          path: info.outputPath("browser-teaching-policy-fixture-" + size.name + ".png"),
        });
      },
    );
  }
});
