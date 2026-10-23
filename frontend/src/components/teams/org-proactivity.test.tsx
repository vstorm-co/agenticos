import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgProactivity } from "./org-proactivity";
import type { Organization } from "@/types";
import { Perm, type Permission } from "@/types/permissions";

/**
 * The organization's proactivity (#2301): off until turned on, never on a model
 * nobody chose, its schedule its own - and the welcome message beside it, each
 * shown only to whoever may change it.
 */

const state = vi.hoisted(() => ({
  held: [] as string[],
  setProactivity: vi.fn(),
  setWelcomeDm: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.held.includes(permission) }),
  useOrganizations: () => ({
    setProactivity: state.setProactivity,
    setWelcomeDm: state.setWelcomeDm,
  }),
  useModelProviders: () => ({
    profiles: [{ id: "mp-1", label: "Haiku", provider: "anthropic", model: "claude-haiku" }],
  }),
  useMcpCatalog: () => ({
    servers: [
      { key: "github", name: "GitHub", icon: "github", url: null },
      { key: "linear", name: "Linear", icon: "linear", url: null },
    ],
  }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
const refusal = vi.hoisted(() => ({
  value: null as null | { fields: Record<string, string>; toast: string | null },
}));
vi.mock("@/lib/api-error", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-error")>();
  return {
    ...actual,
    submitFailure: (...args: Parameters<typeof actual.submitFailure>) =>
      refusal.value ?? actual.submitFailure(...args),
  };
});

const org = (overrides: Partial<Organization> = {}) =>
  ({ id: "o1", name: "Acme", ...overrides }) as unknown as Organization;

const ON = {
  proactive_enabled: true,
  proactive_model_profile_id: "mp-1",
  proactive_limit_usd: "1.000000",
  proactive_days: [1, 2, 3, 4, 5],
  proactive_hour: 5,
  proactive_timing: "fixed" as const,
};

beforeEach(() => {
  state.held = [Perm.budgetsManage, Perm.orgSettings];
  state.setProactivity.mockReset().mockResolvedValue(undefined);
  state.setWelcomeDm.mockReset().mockResolvedValue(undefined);
  refusal.value = null;
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("OrgProactivity", () => {
  it("is not shown to somebody who may change neither setting", () => {
    state.held = [];
    const { container } = render(<OrgProactivity org={org()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each setting only to whoever may change it", () => {
    state.held = [Perm.orgSettings];
    render(<OrgProactivity org={org()} />);

    expect(screen.queryByRole("switch", { name: "Nightly suggestions" })).toBeNull();
    expect(
      screen.getByRole("switch", { name: "Welcome message in chat apps" }),
    ).toBeInTheDocument();
  });

  it("starts off, and is not turned on without a model to run on", async () => {
    render(<OrgProactivity org={org()} />);
    const nightly = screen.getByRole("switch", { name: "Nightly suggestions" });
    expect(nightly).not.toBeChecked();
    expect(screen.queryByLabelText("Model")).toBeNull();

    await userEvent.click(nightly);
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(screen.getByText("Choose the model it runs on before turning it on.")).toBeVisible();
    expect(state.setProactivity).not.toHaveBeenCalled();
  });

  it("saves the whole schedule: model, limit, days, when and the hour", async () => {
    render(<OrgProactivity org={org(ON)} />);
    const days = screen.getByRole("group", { name: "Days" });
    // Friday off, Saturday on.
    await userEvent.click(within(days).getAllByRole("button")[4]!);
    await userEvent.click(within(days).getAllByRole("button")[5]!);
    await userEvent.clear(screen.getByLabelText("Limit per person (USD a month)"));
    await userEvent.type(screen.getByLabelText("Limit per person (USD a month)"), "2");
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(state.setProactivity).toHaveBeenCalledWith("o1", {
      proactive_enabled: true,
      proactive_model_profile_id: "mp-1",
      proactive_limit_usd: 2,
      proactive_days: [1, 2, 3, 4, 6],
      proactive_hour: 5,
      proactive_timing: "fixed",
      proactive_watches_enabled: false,
      proactive_watch_min_minutes: 60,
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions saved"));
  });

  it("does not let watches on without the model they share with the nightly look", async () => {
    render(<OrgProactivity org={org()} />);
    await userEvent.click(screen.getByRole("switch", { name: "Watch people's connections" }));
    // The model and the limit appear for watches alone; the nightly schedule does not.
    expect(screen.getByRole("combobox", { name: "Model" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Days" })).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(screen.getByText("Choose the model it runs on before turning it on.")).toBeVisible();
    expect(state.setProactivity).not.toHaveBeenCalled();
  });

  it("turns watches on with how often at most", async () => {
    render(<OrgProactivity org={org({ proactive_model_profile_id: "mp-1" })} />);
    await userEvent.click(screen.getByRole("switch", { name: "Watch people's connections" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Most often" }));
    await userEvent.click(await screen.findByRole("option", { name: "Every 3 hours" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(state.setProactivity).toHaveBeenCalledWith(
      "o1",
      expect.objectContaining({
        proactive_enabled: false,
        proactive_watches_enabled: true,
        proactive_watch_min_minutes: 180,
      }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions saved"));
  });

  it("shows the floor already saved", () => {
    render(
      <OrgProactivity
        org={org({
          proactive_model_profile_id: "mp-1",
          proactive_watches_enabled: true,
          proactive_watch_min_minutes: 1440,
        })}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Most often" })).toHaveTextContent("Daily");
  });

  it("is turned on with a model from the organization's, before work, at seven", async () => {
    render(<OrgProactivity org={org()} />);
    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    await userEvent.click(await screen.findByRole("option", { name: "Haiku" }));
    await userEvent.click(screen.getByRole("combobox", { name: "When" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "An hour before their working hours" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Hour" }));
    await userEvent.click(await screen.findByRole("option", { name: "07:00" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(state.setProactivity).toHaveBeenCalledWith(
      "o1",
      expect.objectContaining({
        proactive_enabled: true,
        proactive_model_profile_id: "mp-1",
        proactive_timing: "before_work",
        proactive_hour: 7,
      }),
    );
  });

  it("keeps at least one day: the last one cannot be turned off", () => {
    render(<OrgProactivity org={org({ ...ON, proactive_days: [3] })} />);
    const days = within(screen.getByRole("group", { name: "Days" })).getAllByRole("button");

    expect(days[2]).toBeDisabled();
    expect(days[0]).toBeEnabled();
  });

  it("says when the hour is only for people without working hours", async () => {
    render(<OrgProactivity org={org({ ...ON, proactive_timing: "before_work" })} />);
    expect(screen.getByText(/whose profile states no working hours/)).toBeInTheDocument();
  });

  it("refuses a limit that is not an amount, and turning it off says so", async () => {
    render(<OrgProactivity org={org(ON)} />);
    await userEvent.clear(screen.getByLabelText("Limit per person (USD a month)"));
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);
    expect(screen.getByText("Enter an amount in dollars, 0 or more.")).toBeVisible();

    await userEvent.type(screen.getByLabelText("Limit per person (USD a month)"), "1");
    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions are off"));
  });

  it("puts the server's refusal under the field it names", async () => {
    refusal.value = { fields: { proactive_model_profile_id: "Not one of yours" }, toast: null };
    state.setProactivity.mockRejectedValue(new Error("400"));
    render(<OrgProactivity org={org({ ...ON, proactive_hour: 6 })} />);
    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions" }));
    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions" }));
    await userEvent.clear(screen.getByLabelText("Limit per person (USD a month)"));
    await userEvent.type(screen.getByLabelText("Limit per person (USD a month)"), "3");
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(await screen.findByText("Not one of yours")).toBeVisible();
  });

  it("toasts a refusal that names no field", async () => {
    refusal.value = { fields: {}, toast: "Server down" };
    state.setProactivity.mockRejectedValue(new Error("500"));
    render(<OrgProactivity org={org(ON)} />);
    await userEvent.type(screen.getByLabelText("Limit per person (USD a month)"), "0");
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Server down"));
  });

  it("greets in the organization's words, and an empty message is the built-in one", async () => {
    render(<OrgProactivity org={org()} />);
    await userEvent.click(screen.getByRole("switch", { name: "Welcome message in chat apps" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(state.setWelcomeDm).toHaveBeenLastCalledWith("o1", {
      welcome_dm_enabled: true,
      welcome_dm_text: null,
    });

    await userEvent.type(screen.getByLabelText("Message"), "  Hi from the team  ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(state.setWelcomeDm).toHaveBeenLastCalledWith("o1", {
      welcome_dm_enabled: true,
      welcome_dm_text: "Hi from the team",
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Welcome message saved"));
  });

  it("puts a refused greeting under its field, and toasts anything else", async () => {
    refusal.value = { fields: { welcome_dm_text: "Too long" }, toast: "Also this" };
    state.setWelcomeDm.mockRejectedValue(new Error("400"));
    render(<OrgProactivity org={org({ welcome_dm_enabled: true, welcome_dm_text: "Hi" })} />);
    await userEvent.type(screen.getByLabelText("Message"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Too long")).toBeVisible();
    expect(toastError).toHaveBeenCalledWith("Also this");
  });

  it("says nothing more than the field when that is all the refusal named", async () => {
    refusal.value = { fields: { welcome_dm_text: "Too long" }, toast: null };
    state.setWelcomeDm.mockRejectedValue(new Error("400"));
    render(<OrgProactivity org={org({ welcome_dm_enabled: true, welcome_dm_text: "Hi" })} />);
    await userEvent.type(screen.getByLabelText("Message"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Too long")).toBeVisible();
    expect(toastError).not.toHaveBeenCalled();
  });
});
