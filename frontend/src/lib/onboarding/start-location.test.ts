import { expect, it } from "vitest";
import { safeStartLocation } from "./start-location";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";

it.each([
  "https://evil.test/onboarding?start-step=member.task&workspace=org",
  "//evil.test/onboarding?start-step=member.task&workspace=org",
  "/\\evil.test/onboarding",
  "/onboarding?workspace=org",
  "/chat?start-step=member.task&workspace=org",
  "/onboarding?start-step=unknown&workspace=org",
  "/onboarding?start-step=admin.deployment&workspace=org&question=unknown",
  "/onboarding?start-step=member.task&workspace=other",
  "/onboarding?start-step=member.task&workspace=org&draft=private",
  "/onboarding?start-step=member.task&workspace=org&workspace=org",
  "/onboarding?start-step=member.task&workspace=org#private",
  "/onboarding?start-step=member.task&workspace=org&question=access",
])("rejects an invalid or unsafe return location: %s", (href) => {
  expect(safeStartLocation(href, "org")).toBeNull();
  useOnboardingLocationStore.setState({ startLocations: {} });
  useOnboardingLocationStore.getState().rememberStartLocation("user", "org", href);
  expect(useOnboardingLocationStore.getState().startLocations).toEqual({});
});
it.each([
  "/onboarding?start-step=member.context&workspace=org",
  "/onboarding?start-step=member.subscriptions&workspace=org",
  "/onboarding?start-step=admin.subscriptions&workspace=org",
  "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
  "/onboarding?start-step=admin.organization&workspace=org&question=advanced",
])("preserves only the wizard's own navigation URL: %s", (href) => {
  expect(safeStartLocation(href, "org")).toBe(href);
});

it("has no return destination before a location has been observed", () => {
  expect(safeStartLocation(undefined, "org")).toBeNull();
});
it.each(["conversation", "studio", "launchpad"])(
  "preserves validated %s preview steps",
  (variant) => {
    const href = `/onboarding?start-step=admin.models&workspace=org&variant=${variant}`;
    expect(safeStartLocation(href, "org")).toBe(href);
    expect(
      safeStartLocation(
        `/onboarding?start-step=member.tools&workspace=org&variant=${variant}`,
        "org",
      ),
    ).not.toBeNull();
  },
);
it.each([
  "/onboarding?start-step=member.task&workspace=org&variant=unknown",
  "/onboarding?start-step=member.task&workspace=org&variant=studio&variant=launchpad",
])("rejects unsafe or unsupported preview locations %s", (href) =>
  expect(safeStartLocation(href, "org")).toBeNull(),
);

it.each(["admin.models", "member.tools"])("preserves %s in the default Studio layout", (step) => {
  const href = `/onboarding?start-step=${step}&workspace=org`;
  expect(safeStartLocation(href, "org")).toBe(href);
});
