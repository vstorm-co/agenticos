import { beforeEach, expect, it } from "vitest";
import { ONBOARDING_LOCATION_KEY, useOnboardingLocationStore } from "./onboarding-location-store";
import { useOnboardingStore } from "./onboarding-store";
import { startLocationKey } from "@/lib/onboarding/start-location";

const href = "/onboarding?start-step=admin.deployment&workspace=org&question=announcement";
beforeEach(() => {
  useOnboardingLocationStore.setState({ startLocations: {} });
  localStorage.removeItem(ONBOARDING_LOCATION_KEY);
  useOnboardingStore.setState({ isOpen: false });
});
it("restores only navigation after a browser reload", async () => {
  useOnboardingLocationStore.getState().rememberStartLocation("user", "org", href);
  const saved = localStorage.getItem(ONBOARDING_LOCATION_KEY);
  expect(saved).not.toBeNull();
  useOnboardingLocationStore.setState({ startLocations: {} });
  localStorage.setItem(ONBOARDING_LOCATION_KEY, saved!);
  await useOnboardingLocationStore.persist.rehydrate();
  expect(useOnboardingLocationStore.getState().startLocations).toEqual({
    [startLocationKey("user", "org")]: href,
  });
  expect(JSON.parse(saved!).state).toEqual({
    startLocations: { [startLocationKey("user", "org")]: href },
  });
});
it("ignores injected tour/completion fields and invalid persisted locations", async () => {
  localStorage.setItem(
    ONBOARDING_LOCATION_KEY,
    JSON.stringify({
      version: 0,
      state: {
        isOpen: true,
        completed: true,
        dismissed: true,
        startLocations: {
          [startLocationKey("user", "org")]: href,
          [startLocationKey("other", "org")]: "/onboarding?start-step=unknown&workspace=org",
          [startLocationKey("user", "other")]: href,
          invalid: href,
          [JSON.stringify({ user: "user" })]: href,
          [JSON.stringify(["", "org"])]: href,
          [JSON.stringify(["user", null])]: href,
          [JSON.stringify(["user", ""])]: href,
          [startLocationKey("nonstring", "org")]: 42,
          [JSON.stringify([null, "org"])]: href,
          [JSON.stringify(["user"])]: href,
          [JSON.stringify(["user", "org", "extra"])]: href,
          [startLocationKey("bad", "org")]: "https://evil.test/onboarding",
        },
      },
    }),
  );
  await useOnboardingLocationStore.persist.rehydrate();
  expect(useOnboardingLocationStore.getState().startLocations).toEqual({
    [startLocationKey("user", "org")]: href,
  });
  expect(useOnboardingLocationStore.getState()).not.toHaveProperty("completed");
  expect(useOnboardingLocationStore.getState()).not.toHaveProperty("dismissed");
  expect(useOnboardingStore.getState().isOpen).toBe(false);
});
it.each([null, {}, { startLocations: null }, { startLocations: [] }])(
  "rejects malformed persisted state %j",
  async (state) => {
    localStorage.setItem(ONBOARDING_LOCATION_KEY, JSON.stringify({ version: 0, state }));
    await useOnboardingLocationStore.persist.rehydrate();
    expect(useOnboardingLocationStore.getState().startLocations).toEqual({});
  },
);
it("persists removal after server-confirmed completion without clearing another scope", async () => {
  const store = useOnboardingLocationStore.getState();
  store.rememberStartLocation("user", "org", href);
  store.rememberStartLocation("other", "org", href);
  store.clearStartLocation("user", "org");
  await useOnboardingLocationStore.persist.rehydrate();
  expect(useOnboardingLocationStore.getState().startLocations).toEqual({
    [startLocationKey("other", "org")]: href,
  });
});

it("keeps repeated observations idempotent and refuses missing scope", () => {
  const store = useOnboardingLocationStore.getState();
  store.rememberStartLocation("user", "org", href);
  const recorded = useOnboardingLocationStore.getState().startLocations;
  store.rememberStartLocation("user", "org", href);
  expect(useOnboardingLocationStore.getState().startLocations).toBe(recorded);
  store.clearStartLocation("missing", "org");
  expect(useOnboardingLocationStore.getState().startLocations).toBe(recorded);
  store.rememberStartLocation("", "org", href);
  store.rememberStartLocation("user", "", "/onboarding?start-step=member.task&workspace=");
  expect(useOnboardingLocationStore.getState().startLocations).toBe(recorded);
});
