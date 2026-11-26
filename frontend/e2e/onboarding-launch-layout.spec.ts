import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

function proposalSummary(value: unknown): { leadName: string; specialistNames: string[] } {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !("lead" in value) ||
    !("specialists" in value) ||
    !Array.isArray(value.specialists)
  )
    throw new Error("Expected the TeamBuilder proposal response");
  const lead = value.lead;
  if (
    !lead ||
    typeof lead !== "object" ||
    Array.isArray(lead) ||
    !("name" in lead) ||
    typeof lead.name !== "string"
  )
    throw new Error("Expected the proposal lead's name");
  const specialistNames = value.specialists.map((specialist: unknown) => {
    if (
      !specialist ||
      typeof specialist !== "object" ||
      Array.isArray(specialist) ||
      !("name" in specialist) ||
      typeof specialist.name !== "string"
    )
      throw new Error("Expected every proposal specialist to have a name");
    return specialist.name;
  });
  return { leadName: lead.name, specialistNames };
}

test("TeamBuilder keeps step navigation stable while its API proposal loads", async ({ page }) => {
  test.setTimeout(30_000);
  const onboardingResponse = await page.request.get("/api/me/onboarding");
  expect(onboardingResponse.ok()).toBe(true);
  const onboarding: unknown = await onboardingResponse.json();
  if (
    !onboarding ||
    typeof onboarding !== "object" ||
    !("organization_id" in onboarding) ||
    typeof onboarding.organization_id !== "string" ||
    !("agents" in onboarding) ||
    !Array.isArray(onboarding.agents)
  )
    throw new Error("Expected the seeded owner's onboarding workspace");
  expect(
    onboarding.agents.some(
      (agent: unknown) =>
        agent && typeof agent === "object" && "name" in agent && agent.name === SEEDED_AGENT_NAME,
    ),
  ).toBe(true);

  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api\/onboarding\/team-proposal(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });

  try {
    await page.goto("/onboarding");
    const main = page.getByRole("main");
    await expect(main.getByText("Step 1 of 4", { exact: true })).toBeVisible();
    await main.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(main.getByText("Step 2 of 4", { exact: true })).toBeVisible();
    await main.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(main.getByText("Step 3 of 4", { exact: true })).toBeVisible();

    const footer = main.locator("footer");
    const before = await footer.boundingBox();
    if (!before) throw new Error("Expected the TeamBuilder navigation footer");
    const proposalResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/onboarding/team-proposal" &&
        response.request().method() === "POST",
    );
    await main.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(footer.getByRole("button").last()).toBeDisabled();
    await expect(main.getByText("Step 3 of 4", { exact: true })).toBeVisible();
    const whileLoading = await footer.boundingBox();
    if (!whileLoading) throw new Error("Expected the navigation footer while generating");
    expect(Math.abs(whileLoading.y - before.y)).toBeLessThan(2);
    expect(Math.abs(whileLoading.height - before.height)).toBeLessThan(2);

    release();
    const proposalResponse = await proposalResponsePromise;
    expect(proposalResponse.ok()).toBe(true);
    const proposal = proposalSummary(await proposalResponse.json());
    await expect(main.getByText("Step 4 of 4", { exact: true })).toBeVisible();
    await expect(main.getByRole("heading", { name: "Your recommended AI team" })).toBeVisible();
    await expect(main.locator('input[type="text"]').first()).toHaveValue(proposal.leadName);
    expect(proposal.specialistNames.length).toBeGreaterThan(0);
    for (const name of proposal.specialistNames) {
      await expect(main.getByRole("heading", { name, exact: true })).toBeVisible();
    }
  } finally {
    release();
  }
});
