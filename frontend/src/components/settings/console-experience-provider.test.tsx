import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ConsoleExperienceProvider,
  useChatHomeOptions,
  useChatCostsVisible,
  useOnboardingReminderPolicy,
} from "./console-experience-provider";
import { DEFAULT_CHAT_HOME, type ConsoleExperience } from "@/lib/console-experience-api";
const env = vi.hoisted(() => ({
  data: undefined as ConsoleExperience | undefined,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-console-experience", () => ({ useConsoleExperience: () => env }));
function Probe() {
  const home = useChatHomeOptions();
  const costs = useChatCostsVisible();
  const reminder = useOnboardingReminderPolicy();
  return (
    <>
      <p data-testid="costs">{String(costs)}</p>
      <p data-testid="home">{JSON.stringify(home)}</p>
      <p data-testid="reminders">{JSON.stringify(reminder)}</p>
    </>
  );
}
const content = (
  <ConsoleExperienceProvider>
    <Probe />
  </ConsoleExperienceProvider>
);
beforeEach(() => {
  env.data = undefined;
  env.error = null;
});
it("never flashes allowed home items before a saved hidden policy arrives", () => {
  const view = render(content);
  const hidden = { inbox: false, starters: false, greeting: false, feature_hints: false };
  expect(screen.getByTestId("home").textContent).toBe(JSON.stringify(hidden));
  expect(screen.getByTestId("reminders").textContent).toBe(
    JSON.stringify({ enabled: false, snooze_days: 1 }),
  );
  env.data = {
    availability: DEFAULT_CHAT_HOME,
    organization_defaults: {},
    preferences: {},
    effective: hidden,
    reminders: {
      availability: false,
      organization_defaults: {},
      preferences: {},
      effective: { enabled: false, snooze_days: 7 },
    },
  };
  view.rerender(
    <ConsoleExperienceProvider>
      <Probe />
    </ConsoleExperienceProvider>,
  );
  expect(screen.getByTestId("home").textContent).toBe(JSON.stringify(hidden));
  env.data = {
    ...env.data,
    effective: DEFAULT_CHAT_HOME,
    reminders: { ...env.data.reminders, effective: { enabled: true, snooze_days: 3 } },
  };
  view.rerender(
    <ConsoleExperienceProvider>
      <Probe />
    </ConsoleExperienceProvider>,
  );
  expect(screen.getByTestId("home").textContent).toBe(JSON.stringify(DEFAULT_CHAT_HOME));
  expect(screen.getByTestId("reminders").textContent).toBe(
    JSON.stringify({ enabled: true, snooze_days: 3 }),
  );
});
it("keeps unknown policies quiet when the initial read fails", () => {
  env.error = new Error("offline");
  render(content);
  expect(screen.getByTestId("home")).toHaveTextContent('"inbox":false');
  expect(screen.getByTestId("reminders")).toHaveTextContent('"enabled":false');
});

it("withholds cached costs on a failed policy refresh", () => {
  env.data = {
    availability: DEFAULT_CHAT_HOME,
    organization_defaults: {},
    preferences: {},
    effective: DEFAULT_CHAT_HOME,
    reminders: {
      availability: true,
      organization_defaults: {},
      preferences: {},
      effective: { enabled: true, snooze_days: 1 },
    },
    costs: {
      availability: true,
      organization_policy: "everyone",
      preference: null,
      permitted: true,
      effective: true,
    },
  };
  const view = render(content);
  expect(screen.getByTestId("costs").textContent).toBe("true");
  env.data = { ...env.data, costs: { ...env.data.costs!, effective: false } };
  view.rerender(content);
  // A new element is required for a context provider to observe the changed query result.
  view.rerender(
    <ConsoleExperienceProvider>
      <Probe />
    </ConsoleExperienceProvider>,
  );
  expect(screen.getByTestId("costs").textContent).toBe("false");
  env.error = new Error("offline");
  view.rerender(
    <ConsoleExperienceProvider>
      <Probe />
    </ConsoleExperienceProvider>,
  );
  expect(screen.getByTestId("costs").textContent).toBe("false");
});
