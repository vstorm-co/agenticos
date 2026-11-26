import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("teammate cards keep their height when Architect finishes loading", async ({ page }) => {
  const response = await page.request.get("/api/me/onboarding");
  expect(response.ok()).toBe(true);
  const state: unknown = await response.json();
  if (
    !state ||
    typeof state !== "object" ||
    !("organization_id" in state) ||
    typeof state.organization_id !== "string" ||
    !("agents" in state) ||
    !Array.isArray(state.agents)
  )
    throw new Error("Expected the seeded owner's onboarding workspace");
  expect(
    state.agents.some(
      (agent: unknown) =>
        agent && typeof agent === "object" && "name" in agent && agent.name === SEEDED_AGENT_NAME,
    ),
  ).toBe(true);

  let release = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/assistant", async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    const assistant: unknown = await response.json();
    if (!assistant || typeof assistant !== "object" || Array.isArray(assistant))
      throw new Error("Expected the workspace Architect");
    await pending;
    // Only simulate the presentation's ready branch; the test never opens the
    // agent or submits a model request, and retains the authenticated workspace.
    await route.fulfill({
      response,
      json: { ...assistant, name: "Architect", status: "ready", can_use: true },
    });
  });
  try {
    const workspace = encodeURIComponent(state.organization_id);
    await page.goto(`/onboarding?variant=studio&start-step=admin.task&workspace=${workspace}`);
    const card = page.locator('[data-start-launch-agent="architect"]');
    await expect(card.getByRole("status")).toBeVisible();
    await expect(
      page.locator('[data-start-launch-agent="agenticos"]').getByRole("status"),
    ).toHaveCount(0);
    const before = await card.boundingBox();
    const footer = page.locator("[data-start-navigation]");
    const footerBefore = await footer.boundingBox();
    if (!before || !footerBefore) throw new Error("Expected the pending card and fixed footer");

    release();
    await expect(card.getByRole("button", { name: "Build with Architect" })).toBeVisible();
    const after = await card.boundingBox();
    const footerAfter = await footer.boundingBox();
    if (!after || !footerAfter) throw new Error("Expected the ready card and fixed footer");
    expect(Math.abs(after.height - before.height)).toBeLessThan(2);
    expect(Math.abs(footerAfter.y - footerBefore.y)).toBeLessThan(2);

    const content = await page.locator("[data-start-content]").boundingBox();
    if (!content) throw new Error("Expected the Studio scroll area");
    expect(content.x + content.width - (after.x + after.width)).toBeGreaterThanOrEqual(16);
  } finally {
    release();
  }
});
