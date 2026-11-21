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
  "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
  "/onboarding?start-step=admin.organization&workspace=org&question=advanced",
])("preserves only the wizard's own navigation URL: %s", (href) => {
  expect(safeStartLocation(href, "org")).toBe(href);
});

it("has no return destination before a location has been observed", () => {
  expect(safeStartLocation(undefined, "org")).toBeNull();
});
