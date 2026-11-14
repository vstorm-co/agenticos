import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, rowsAt, submitDialog } from "./helpers";
import type { APIResponse, Page } from "@playwright/test";

async function createdId(response: Pick<APIResponse, "ok" | "status" | "json">): Promise<string> {
  expect(response.ok(), `write answered ${response.status()}`).toBe(true);
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    !("id" in value) ||
    typeof value.id !== "string"
  )
    throw new Error("Missing resource id");
  return value.id;
}
async function heldRefusal(page: Page, path: string, method: "POST" | "DELETE") {
  let release!: () => void;
  let began!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const started = new Promise<void>((resolve) => {
    began = resolve;
  });
  const pattern = `**${path}`;
  await page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.continue();
    began();
    await held;
    await route.fulfill({ status: 403, json: { detail: "Controlled department write refusal" } });
  });
  return { started, release, remove: () => page.unroute(pattern) };
}

for (const device of [
  { name: "desktop", viewport: { width: 1440, height: 1000 }, phone: false },
  { name: "phone", viewport: { width: 320, height: 740 }, phone: true },
] as const) {
  test.describe(device.name, () => {
    test.use({
      storageState: AUTH_STATE,
      actionTimeout: 15_000,
      viewport: device.viewport,
      hasTouch: device.phone,
      isMobile: device.phone,
      reducedMotion: "reduce",
    });
    test("department identity, membership, sharing and deletion survive refusals and reload", async ({
      page,
    }) => {
      test.setTimeout(120_000);
      const org = (await rowsAt(page.request, "/api/orgs"))[0];
      if (!org || typeof org.id !== "string") throw new Error("Missing seeded organization");
      const groupPath = `/api/orgs/${org.id}/groups`;
      const owner = (await rowsAt(page.request, `/api/orgs/${org.id}/members`)).find(
        (member) => member.role === "owner",
      );
      if (!owner || typeof owner.user_id !== "string" || typeof owner.email !== "string")
        throw new Error("Missing owner membership");
      const ownerName =
        typeof owner.full_name === "string" && owner.full_name ? owner.full_name : owner.email;
      const ownerOption =
        typeof owner.full_name === "string" && owner.full_name
          ? `${owner.full_name} (${owner.email})`
          : owner.email;
      const stamp = Date.now().toString(36);
      const name = `Support & Customer Experience ${stamp}`;
      const fileName = `ui-department-handbook-${stamp}.md`;
      let groupId: string | undefined;
      let contextId: string | undefined;
      let release: (() => void) | undefined;
      try {
        contextId = await createdId(
          await page.request.post("/api/context", {
            data: {
              name: fileName,
              description: "Shared customer support guidance.",
              content: "Always include the customer and the next action.",
              mode: "link",
              visibility: "private",
            },
          }),
        );
        await page.goto("/groups");
        await page.getByRole("button", { name: "New group", exact: true }).first().click();
        const dialog = page.getByRole("dialog");
        await dialog.getByLabel("Name", { exact: true }).fill(name);
        await dialog
          .getByLabel("Description", { exact: true })
          .fill("Questions, customer handovers and reusable support guidance.");
        await dialog.getByRole("button", { name: "Handshake", exact: true }).click();
        await expect(
          dialog.getByRole("button", { name: "Handshake", exact: true }),
        ).toHaveAttribute("aria-pressed", "true");
        await dialog.getByRole("button", { name: "Budget limit", exact: true }).click();
        await dialog.getByLabel("Monthly budget (USD)", { exact: true }).fill("80");
        const createHeld = await heldRefusal(page, groupPath, "POST");
        release = createHeld.release;
        await dialog.getByRole("button", { name: "Create", exact: true }).click();
        await createHeld.started;
        await expect(dialog.getByLabel("Name", { exact: true })).toBeDisabled();
        await expect(dialog.getByRole("button", { name: "Handshake", exact: true })).toBeDisabled();
        for (const button of ["Cancel", "Close"])
          await expect(dialog.getByRole("button", { name: button, exact: true })).toBeDisabled();
        await page.keyboard.press("Escape");
        await expect(dialog).toBeVisible();
        createHeld.release();
        await expect(dialog.getByLabel("Name", { exact: true })).toBeEnabled();
        await createHeld.remove();
        await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(name);
        await expect(dialog.getByLabel("Monthly budget (USD)", { exact: true })).toHaveValue("80");
        await submitDialog(page, {
          dialog,
          submit: dialog.getByRole("button", { name: "Create", exact: true }),
          path: groupPath,
        });
        const group = await nowMatching(page.request, groupPath, (row) => row.name === name, name);
        if (typeof group.id !== "string") throw new Error("Missing created group id");
        groupId = group.id;
        await page.getByPlaceholder("Search departments…").fill(name);
        await expect(
          page.getByRole("button", { name: `Members of ${name}`, exact: true }),
        ).toContainText("0 members");
        await page.getByRole("link", { name, exact: true }).click();
        await expect(page).toHaveURL(new RegExp(`/groups/${groupId}$`));
        await page.getByRole("button", { name: "0 members", exact: true }).click();
        await dialog.getByRole("combobox", { name: "Add a member", exact: true }).click();
        await page.getByRole("option", { name: ownerOption, exact: true }).click();
        const membersPath = `${groupPath}/${groupId}/members`;
        const memberHeld = await heldRefusal(page, membersPath, "POST");
        release = memberHeld.release;
        await dialog.getByRole("button", { name: "Add", exact: true }).click();
        await memberHeld.started;
        await expect(
          dialog.getByRole("combobox", { name: "Add a member", exact: true }),
        ).toBeDisabled();
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
        await page.keyboard.press("Escape");
        await expect(dialog).toBeVisible();
        memberHeld.release();
        await expect(
          dialog.getByRole("combobox", { name: "Add a member", exact: true }),
        ).toBeEnabled();
        await memberHeld.remove();
        await expect(
          dialog.getByRole("combobox", { name: "Add a member", exact: true }),
        ).toContainText(ownerName);
        const added = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === membersPath &&
            response.request().method() === "POST" &&
            response.ok(),
        );
        await dialog.getByRole("button", { name: "Add", exact: true }).click();
        await added;
        const memberRow = dialog.getByRole("group", { name: ownerName, exact: true });
        await expect(memberRow).toBeVisible();
        if (await dialog.getByRole("combobox", { name: "Add a member", exact: true }).count())
          await expect(
            dialog.getByRole("combobox", { name: "Add a member", exact: true }),
          ).not.toContainText(ownerName);
        await memberRow
          .getByRole("button", { name: `Make ${ownerName} the group's lead`, exact: true })
          .click();
        await expect(memberRow.getByText("Lead", { exact: true })).toBeVisible();
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
        await page.locator('[data-tour="group-add-to"]').click();
        if (device.phone) {
          const frame = await dialog.boundingBox();
          const button = await dialog
            .getByRole("button", { name: "Share", exact: true })
            .boundingBox();
          const access = await dialog.getByRole("combobox").boundingBox();
          expect(frame).not.toBeNull();
          expect(button).not.toBeNull();
          expect(access).not.toBeNull();
          if (frame && button && access) {
            expect(button.width).toBeGreaterThan(frame.width - 60);
            expect(access.width).toBeGreaterThan(frame.width - 60);
          }
        }
        await dialog.getByRole("textbox").fill(fileName);
        await dialog.getByRole("checkbox", { name: fileName, exact: true }).click();
        await dialog.getByRole("combobox").click();
        await page.getByRole("option", { name: "can view", exact: true }).click();
        const sharesPath = `${groupPath}/${groupId}/shares`;
        const shareHeld = await heldRefusal(page, sharesPath, "POST");
        release = shareHeld.release;
        await dialog.getByRole("button", { name: "Share 1", exact: true }).click();
        await shareHeld.started;
        await expect(dialog.getByRole("checkbox", { name: fileName, exact: true })).toBeDisabled();
        await expect(dialog.getByRole("combobox")).toBeDisabled();
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
        shareHeld.release();
        await expect(dialog.getByRole("combobox")).toBeEnabled();
        await shareHeld.remove();
        await expect(dialog.getByRole("checkbox", { name: fileName, exact: true })).toBeChecked();
        await expect(dialog.getByRole("combobox")).toContainText("can view");
        await submitDialog(page, {
          dialog,
          submit: dialog.getByRole("button", { name: "Share 1", exact: true }),
          path: sharesPath,
        });
        await expect(page.getByText(fileName, { exact: true })).toBeVisible();
        const resource = await nowMatching(
          page.request,
          `${groupPath}/${groupId}/resources`,
          (row) => row.id === contextId,
          fileName,
        );
        expect(resource.level).toBe("read");
        if (device.phone) {
          await page.getByRole("button", { name: "More page actions", exact: true }).click();
          await page.setViewportSize({ width: 320, height: 568 });
        }
        await page.getByRole("button", { name: "Edit group", exact: true }).click();
        await dialog.getByLabel("Name", { exact: true }).fill(`${name} updated`);
        await dialog
          .getByLabel("Description", { exact: true })
          .fill("Customer guidance, handovers and support ownership.");
        await dialog.getByRole("button", { name: "Code", exact: true }).click();
        await dialog.getByLabel("Monthly budget (USD)", { exact: true }).fill("90");
        const save = dialog.getByRole("button", { name: "Save", exact: true });
        const bounds = await save.boundingBox();
        expect(bounds).not.toBeNull();
        if (bounds) expect(bounds.y + bounds.height).toBeLessThanOrEqual(device.phone ? 568 : 1000);
        await submitDialog(page, {
          dialog,
          submit: save,
          path: `${groupPath}/${groupId}`,
          method: "PATCH",
        });
        if (device.phone) await page.setViewportSize(device.viewport);
        const edited = await nowMatching(
          page.request,
          groupPath,
          (row) => row.id === groupId && row.name === `${name} updated`,
          "renamed department",
        );
        expect(edited.icon).toBe("code");
        expect(edited.monthly_budget_usd).toMatch(/^90(?:\.0+)?$/);
        await page.reload();
        await expect(
          page.getByRole("heading", { name: `${name} updated`, exact: true }),
        ).toBeVisible();
        await expect(page.getByText(fileName, { exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: "1 member", exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
          device.viewport.width,
        );
        await page.getByRole("main").getByRole("link", { name: "Groups", exact: true }).click();
        await page.getByPlaceholder("Search departments…").fill(`${name} updated`);
        await page.getByRole("button", { name: `Remove ${name} updated`, exact: true }).click();
        const removePath = `${groupPath}/${groupId}`;
        const removeHeld = await heldRefusal(page, removePath, "DELETE");
        release = removeHeld.release;
        await dialog.getByRole("button", { name: "Delete", exact: true }).click();
        await removeHeld.started;
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
        removeHeld.release();
        await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeEnabled();
        await removeHeld.remove();
        await expect(dialog).toBeVisible();
        await submitDialog(page, {
          dialog,
          submit: dialog.getByRole("button", { name: "Delete", exact: true }),
          path: removePath,
          method: "DELETE",
        });
        groupId = undefined;
        await expect(page.getByRole("link", { name: `${name} updated`, exact: true })).toHaveCount(
          0,
        );
      } finally {
        release?.();
        if (groupId) expect((await page.request.delete(`${groupPath}/${groupId}`)).ok()).toBe(true);
        if (contextId)
          expect((await page.request.delete(`/api/context/${contextId}`)).ok()).toBe(true);
      }
    });
  });
}
