import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";
import type { CodingAccount, CodingAccountUsage } from "../src/lib/coding-accounts-api";

test.use({ storageState: AUTH_STATE });

/**
 * Visual fixtures on the real Profile page, with synthetic owner metadata.
 * These images prove current-source layout, not a live provider observation.
 * The regular Profile screenshots still exercise the real backend separately.
 */
for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  for (const scenario of [
    "populated",
    "stale-refresh",
    "revoked-read",
    "revoked-refresh",
  ] as const) {
    test(`captures synthetic ${scenario} coding usage at ${viewport.name} width`, async ({
      page,
    }, testInfo) => {
      testInfo.annotations.push({
        type: "visual-fixture",
        description:
          "Synthetic owned-account reports and intercepted refresh acknowledgments on the real Profile page. No provider/key use or model execution; live-account acceptance is unverified.",
      });
      const now = Date.now();
      const observedAt = new Date(now - 12_000).toISOString();
      const validUntil = new Date(
        now + (scenario === "stale-refresh" ? -1_000 : 300_000),
      ).toISOString();
      const firstReset = new Date(now + 2 * 60 * 60_000).toISOString();
      const secondReset = new Date(now + 4 * 24 * 60 * 60_000).toISOString();
      const codex: CodingAccount = {
        id: "00000000-0000-4000-8000-000000000114",
        harness: "codex",
        label: "Synthetic Codex account",
        secret_kind: "openai_codex",
        enabled: true,
        generation: "visual-generation",
        is_default: true,
        pool_member: true,
        usage_refresh_pending: false,
        usage: {
          status: "available",
          source: "native_runtime",
          observed_at: observedAt,
          observation_age_seconds: 12,
          valid_until: validUntil,
          reason_code: null,
          windows: [
            {
              name: "primary",
              used: 37,
              limit: 100,
              unit: "percent",
              resets_at: firstReset,
              window_duration_minutes: 300,
            },
            {
              name: "secondary",
              used: 74,
              limit: 100,
              unit: "percent",
              resets_at: secondReset,
              window_duration_minutes: 10080,
            },
          ],
        },
        model_catalog: {
          status: "advertised",
          source: "native_runtime",
          observed_at: observedAt,
          valid_until: validUntil,
          model_ids: ["synthetic-model-alpha", "synthetic-model-beta"],
          reason_code: null,
        },
      };
      const claude: CodingAccount = {
        ...codex,
        id: "00000000-0000-4000-8000-000000000115",
        harness: "claude_code",
        label: "Synthetic Claude account",
        secret_kind: "api_key",
        pool_member: false,
        usage: {
          status: "unknown",
          source: "unavailable",
          observed_at: null,
          observation_age_seconds: null,
          valid_until: null,
          windows: [],
          reason_code: "telemetry_unsupported",
        },
        model_catalog: {
          status: "unknown",
          source: "unavailable",
          observed_at: null,
          valid_until: null,
          model_ids: [],
          reason_code: "model_catalog_unverified",
        },
      };
      const report: CodingAccountUsage = {
        account_id: codex.id,
        generation: codex.generation,
        usage: codex.usage,
        model_catalog: codex.model_catalog,
        refresh_pending: false,
      };
      const unexpected: string[] = [];
      const organizations = new Set<string>();
      const refusedStatus = viewport.name === "desktop" ? 403 : 404;
      const refusal = { code: "NOT_FOUND", message: "Synthetic account access was revoked" };
      let releaseRead!: () => void;
      const readGate = new Promise<void>((resolve) => {
        releaseRead = resolve;
      });
      let releaseRefreshedRead!: () => void;
      const refreshedReadGate = new Promise<void>((resolve) => {
        releaseRefreshedRead = resolve;
      });
      let refreshPosts = 0;
      let reads = 0;
      let refreshAccepted = false;
      const refreshedReport: CodingAccountUsage = {
        ...report,
        usage: {
          ...report.usage,
          valid_until: new Date(now + 300_000).toISOString(),
          windows: [
            { name: "primary", used: 61, limit: 100, unit: "percent", resets_at: firstReset },
          ],
        },
        model_catalog: {
          ...report.model_catalog,
          valid_until: new Date(now + 300_000).toISOString(),
          model_ids: ["synthetic-refreshed-model"],
        },
      };
      await page.route("**/api/coding-accounts**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(/\/$/, "");
        organizations.add(route.request().headers()["x-organization-id"] ?? "");
        if (route.request().method() === "GET" && path === "/api/coding-accounts") {
          // A stale list response cannot restore usage evidence after its own read was refused.
          await route.fulfill({ json: { items: [claude, codex] } });
        } else if (
          route.request().method() === "GET" &&
          path === `/api/coding-accounts/${codex.id}/usage`
        ) {
          if (scenario === "revoked-read") {
            await readGate;
            await route.fulfill({ status: refusedStatus, json: refusal });
          } else if (refreshAccepted) {
            await refreshedReadGate;
            await route.fulfill({ json: refreshedReport });
          } else {
            await route.fulfill({ json: report });
          }
          reads += 1;
        } else if (
          route.request().method() === "POST" &&
          path === `/api/coding-accounts/${codex.id}/usage/refresh` &&
          (scenario === "stale-refresh" || scenario === "revoked-refresh")
        ) {
          refreshPosts += 1;
          const payload: unknown = route.request().postDataJSON();
          if (JSON.stringify(payload) !== JSON.stringify({ generation: codex.generation })) {
            unexpected.push("Refresh did not pin the reviewed account generation");
            await route.fulfill({
              status: 409,
              json: { message: "Synthetic generation mismatch" },
            });
          } else if (scenario === "revoked-refresh") {
            await route.fulfill({ status: refusedStatus, json: refusal });
          } else {
            refreshAccepted = true;
            await route.fulfill({ status: 202, json: { ...report, refresh_pending: true } });
          }
        } else {
          unexpected.push(`${route.request().method()} ${path}`);
          // No account mutation or real provider refresh can escape this fixture.
          await route.fulfill({
            status: 400,
            json: { detail: "Unexpected visual fixture request" },
          });
        }
      });
      try {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto("/settings/profile");
        const section = page.locator('section:has(> header[data-tour="personal-coding-accounts"])');
        const usage = section.getByRole("region", { name: "Usage for Synthetic Codex account" });
        const refresh = usage.getByRole("button", { name: "Refresh usage", exact: true });
        await expect(section.getByText("Synthetic Claude account", { exact: true })).toBeVisible();
        await expect(
          section.getByText("Usage reporting is not supported for this connection.", {
            exact: true,
          }),
        ).toBeVisible();
        await expect(
          section
            .getByRole("region", { name: "Usage for Synthetic Claude account" })
            .getByRole("button", { name: "Refresh usage", exact: true }),
        ).toHaveCount(0);
        expect(refreshPosts).toBe(0);
        if (scenario === "stale-refresh") {
          await expect(
            usage.getByText("This usage report has expired. Refresh for a current report.", {
              exact: true,
            }),
          ).toBeVisible();
          await expect(usage.getByText("Reported status: Unknown", { exact: true })).toBeVisible();
          await expect(usage.getByText("37 / 100 %", { exact: true })).toHaveCount(0);
          await expect(usage.getByText("synthetic-model-alpha", { exact: true })).toHaveCount(0);
          await section.screenshot({
            path: testInfo.outputPath(`synthetic-coding-usage-stale-${viewport.name}.png`),
          });
        } else {
          await expect(
            usage.getByText("Reported status: Available", { exact: true }),
          ).toBeVisible();
          await expect(
            usage.getByText("Source: Native account report", { exact: true }),
          ).toHaveCount(2);
          await expect(usage.locator(`time[datetime="${observedAt}"]`)).toHaveCount(2);
          await expect(usage.locator(`time[datetime="${validUntil}"]`)).toHaveCount(2);
          await expect(usage.locator(`time[datetime="${firstReset}"]`)).toHaveCount(1);
          await expect(usage.locator(`time[datetime="${secondReset}"]`)).toHaveCount(1);
          await expect(usage.getByText("37 / 100 %", { exact: true })).toBeVisible();
          await expect(usage.getByText("synthetic-model-alpha", { exact: true })).toBeVisible();
        }
        await expect(refresh).toBeEnabled();
        if (scenario !== "revoked-read") await expect.poll(() => reads).toBeGreaterThan(0);
        if (scenario === "revoked-read") {
          const denied = page.waitForResponse(
            (response) =>
              response.request().method() === "GET" &&
              new URL(response.url()).pathname === `/api/coding-accounts/${codex.id}/usage`,
          );
          releaseRead();
          expect((await denied).status()).toBe(refusedStatus);
        } else if (scenario === "stale-refresh" || scenario === "revoked-refresh") {
          const submitted = page.waitForResponse(
            (response) =>
              response.request().method() === "POST" &&
              new URL(response.url()).pathname === `/api/coding-accounts/${codex.id}/usage/refresh`,
          );
          await refresh.click();
          expect((await submitted).status()).toBe(
            scenario === "stale-refresh" ? 202 : refusedStatus,
          );
          expect(refreshPosts).toBe(1);
        }
        if (scenario === "revoked-read" || scenario === "revoked-refresh") {
          await expect(
            usage.getByText("This connection changed. Checking its current status.", {
              exact: true,
            }),
          ).toBeVisible();
          await expect(usage.getByText("Reported status: Unknown", { exact: true })).toBeVisible();
          await expect(usage.getByText("37 / 100 %", { exact: true })).toHaveCount(0);
          await expect(usage.getByText("synthetic-model-alpha", { exact: true })).toHaveCount(0);
          await expect(refresh).toBeDisabled();
        } else if (scenario === "stale-refresh") {
          await expect(usage.getByText("Usage refresh is pending.", { exact: true })).toBeVisible();
          await expect(refresh).toBeDisabled();
          await section.screenshot({
            path: testInfo.outputPath(`synthetic-coding-usage-pending-${viewport.name}.png`),
          });
          releaseRefreshedRead();
          await expect(usage.getByText("synthetic-refreshed-model", { exact: true })).toBeVisible();
          await expect(usage.getByText("61 / 100 %", { exact: true })).toBeVisible();
          await expect(refresh).toBeEnabled();
        }
        expect(refreshPosts).toBe(
          scenario === "stale-refresh" || scenario === "revoked-refresh" ? 1 : 0,
        );
        expect(unexpected).toEqual([]);
        expect(organizations.size).toBe(1);
        expect([...organizations][0]).toMatch(/^[0-9a-f-]{36}$/i);
        expect(
          await section.evaluate((element) => element.scrollWidth - element.clientWidth),
        ).toBeLessThanOrEqual(1);
        await section.screenshot({
          path: testInfo.outputPath(`synthetic-coding-usage-${scenario}-${viewport.name}.png`),
        });
      } finally {
        releaseRead();
        releaseRefreshedRead();
      }
    });
  }
}
