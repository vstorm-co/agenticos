import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentContextSettings } from "./agent-context-settings";
import type { User } from "@/types";

/** What every agent is told about the person, written once in Settings (#2301). */

const save = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-account-profile", () => ({ useSaveAgentContext: () => save }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

function user(overrides: Partial<User> = {}): User {
  return { id: "u-1", job_title: null, about: null, time_zone: null, ...overrides } as User;
}

beforeEach(() => {
  save.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("AgentContextSettings", () => {
  it("opens on what the account holds", () => {
    render(
      <AgentContextSettings
        user={user({ job_title: "CFO", about: "Budgets", time_zone: "UTC" })}
      />,
    );

    expect(screen.getByLabelText("Your role")).toHaveValue("CFO");
    expect(screen.getByLabelText("What you work on")).toHaveValue("Budgets");
    expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveTextContent("UTC");
  });

  it("saves what was typed, trimmed, and says agents know it", async () => {
    save.mockResolvedValue(user());
    render(<AgentContextSettings user={user()} />);

    await userEvent.type(screen.getByLabelText("Your role"), "  Head of sales ");
    await userEvent.click(screen.getByRole("combobox", { name: "Time zone" }));
    await userEvent.type(screen.getByRole("combobox", { name: "Search time zones…" }), "Warsaw");
    await userEvent.click(screen.getByRole("option", { name: "Europe/Warsaw" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save).toHaveBeenCalledWith({
      job_title: "Head of sales",
      about: null,
      time_zone: "Europe/Warsaw",
      working_hours: null,
    });
    expect(toastSuccess).toHaveBeenCalledWith("Saved - your agents know it from the next message.");
  });

  it("clears a field emptied, rather than keeping what was there", async () => {
    save.mockResolvedValue(user());
    render(
      <AgentContextSettings
        user={user({ job_title: "CFO", about: "Budgets", time_zone: "UTC" })}
      />,
    );

    await userEvent.clear(screen.getByLabelText("Your role"));
    await userEvent.clear(screen.getByLabelText("What you work on"));
    await userEvent.click(screen.getByRole("combobox", { name: "Time zone" }));
    await userEvent.click(screen.getByRole("option", { name: "Not set" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save).toHaveBeenCalledWith({
      job_title: null,
      about: null,
      time_zone: null,
      working_hours: null,
    });
  });

  it("says why a save was refused and lets it be tried again", async () => {
    save.mockRejectedValue(new Error("Unknown time zone"));
    render(<AgentContextSettings user={user()} />);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(toastError).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("follows the account when it changes elsewhere - the tour's role, another tab", () => {
    const { rerender } = render(<AgentContextSettings user={user()} />);

    rerender(<AgentContextSettings user={user({ job_title: "Sales" })} />);

    expect(screen.getByLabelText("Your role")).toHaveValue("Sales");
  });

  it("saves working hours from a picked day, nine to five until changed", async () => {
    save.mockResolvedValue(user());
    render(<AgentContextSettings user={user()} />);
    expect(screen.queryByLabelText("Starts at")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Wed" }));
    await userEvent.click(screen.getByRole("button", { name: "Mon" }));
    await userEvent.clear(screen.getByLabelText("Ends at"));
    await userEvent.type(screen.getByLabelText("Ends at"), "16:00");
    await userEvent.clear(screen.getByLabelText("Starts at"));
    await userEvent.type(screen.getByLabelText("Starts at"), "08:30");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save.mock.calls[0]?.[0].working_hours).toEqual({
      days: [1, 3],
      start: "08:30",
      end: "16:00",
    });
    expect(screen.getByRole("button", { name: "Mon" })).toHaveAttribute("aria-pressed", "true");
  });

  it("clears working hours when the last day is taken off", async () => {
    save.mockResolvedValue(user());
    render(
      <AgentContextSettings
        user={user({ working_hours: { days: [2], start: "08:00", end: "12:00" } })}
      />,
    );
    expect(screen.getByLabelText("Starts at")).toHaveValue("08:00");

    await userEvent.click(screen.getByRole("button", { name: "Tue" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save.mock.calls[0]?.[0].working_hours).toBeNull();
  });
});

it("advances guided setup only after profile and context saves succeed", async () => {
  const beforeSave = vi.fn().mockResolvedValue(false);
  const onSaved = vi.fn();
  save.mockResolvedValue(user());
  render(
    <AgentContextSettings
      user={user()}
      beforeSave={beforeSave}
      onSaved={onSaved}
      saveLabel="Save and continue"
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(save).not.toHaveBeenCalled();
  expect(onSaved).not.toHaveBeenCalled();
  beforeSave.mockResolvedValue(true);
  save.mockRejectedValueOnce(new Error("offline"));
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(onSaved).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(onSaved).toHaveBeenCalledOnce();
});

it("highlights the next empty context field without treating it as an error", async () => {
  render(<AgentContextSettings user={user()} onSaved={() => {}} saveLabel="Continue" />);
  const role = screen.getByRole("textbox", { name: "Your role" });
  expect(role).toHaveAttribute("data-guidance", "true");
  await userEvent.type(role, "Engineer");
  expect(role).not.toHaveAttribute("data-guidance");
  expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveAttribute(
    "data-guidance",
    "true",
  );
});

it("filters time zones and selects the match with the keyboard", async () => {
  save.mockResolvedValue(user());
  render(<AgentContextSettings user={user()} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Time zone" }));
  await userEvent.type(screen.getByRole("combobox", { name: "Search time zones…" }), "Warsaw");
  expect(screen.queryByRole("option", { name: "Africa/Algiers" })).not.toBeInTheDocument();
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveTextContent("Europe/Warsaw");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[0]?.[0].time_zone).toBe("Europe/Warsaw");
});

it("shows an empty result and lets Escape preserve the stored alias", async () => {
  render(<AgentContextSettings user={user({ time_zone: "US/Eastern" })} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Time zone" }));
  expect(screen.getByRole("option", { name: "US/Eastern" })).toBeVisible();
  await userEvent.type(
    screen.getByRole("combobox", { name: "Search time zones…" }),
    "no-such-zone",
  );
  expect(screen.getByText("No matching time zones")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveTextContent("US/Eastern");
});

it("rejects an extra form submission while the first save is pending", async () => {
  let complete!: (value: User) => void;
  save.mockImplementation(
    () =>
      new Promise<User>((resolve) => {
        complete = resolve;
      }),
  );
  render(<AgentContextSettings user={user()} />);
  const button = screen.getByRole("button", { name: "Save" });
  await userEvent.click(button);
  const form = button.closest("form");
  if (!form) throw new Error("Missing context form");
  fireEvent.submit(form);
  expect(save).toHaveBeenCalledOnce();
  complete(user());
});
