import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_HANDLE, nowMatching } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("Improve opens over the current agent tab and closes with Cancel or Back", async ({
  page,
}) => {
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  const agent = await nowMatching(
    page.request,
    "/api/agents?limit=100",
    (row) => row.slug === SEEDED_AGENT_HANDLE.slice(1),
    "the bootstrapped agent",
  );
  if (typeof agent.id !== "string") throw new Error("The bootstrapped agent has no id");
  await page.goto(`/agents/${agent.id}?tab=history`);
  const openSetup = async () => {
    const more = page.locator('[data-tour="page-secondary-actions"]');
    if ((await more.getAttribute("aria-expanded")) !== "true") await more.click();
    await page.locator('[data-tour="agent-improve"]').click();
  };
  await openSetup();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/tab=history.*improve=new/);
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Start improving", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/tab=history$/);
  await openSetup();
  await expect(dialog).toBeVisible();
  await page.goBack();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/tab=history$/);

  await openSetup();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/tab=history$/);

  await page.goto(`/agents/${agent.id}/improve/new?baseline=1`);
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent.id}[?]improve=baseline$`));
  await expect(dialog.getByText(/Set a baseline/)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent.id}$`));
});
