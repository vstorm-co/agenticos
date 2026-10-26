import { expect, test } from "./fixtures";
import { AUTH_STATE, walkPageTour } from "./helpers";

/**
 * A page's "?" walked from its first stop to its last. A stop that names a tab
 * opens that tab itself, and no stop holds the walk with its buttons greyed.
 */
test.use({ storageState: AUTH_STATE });

test("a dataset's tour opens each tab it describes and runs to its end", async ({ page }) => {
  await page.goto("/datasets");
  const organizationId = await page.evaluate(() => {
    const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
    if (typeof value !== "object" || value === null || !("state" in value)) return "";
    const state = value.state as { activeOrgId?: unknown };
    return typeof state.activeOrgId === "string" ? state.activeOrgId : "";
  });
  const headers = { "X-Organization-Id": organizationId };
  const created = await page.request.post("/api/datasets", {
    headers,
    data: { name: `Tour walk ${Date.now().toString(36)}` },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };
  const added = await page.request.post(`/api/datasets/${id}/cases`, {
    headers,
    data: { input: "How long is the refund window?", checks: [{ type: "contains", value: "30" }] },
  });
  expect(added.ok(), await added.text()).toBeTruthy();

  await page.goto(`/datasets/${id}`);
  const tabFor: Record<string, string> = {
    "Have cases drafted": "Generated",
    "How cases are graded": "Grading",
    "The judge": "Grading",
    Review: "Review",
  };
  const seen = await walkPageTour(page, async (title) => {
    const tab = tabFor[title];
    if (tab)
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("data-state", "active");
  });
  expect(seen).toEqual(
    expect.arrayContaining(["Write a case", "How cases are graded", "The judge", "Review"]),
  );
});
