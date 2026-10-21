import { render, screen } from "@testing-library/react";
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
    expect(screen.getByLabelText("Time zone")).toHaveValue("UTC");
  });

  it("saves what was typed, trimmed, and says agents know it", async () => {
    save.mockResolvedValue(user());
    render(<AgentContextSettings user={user()} />);

    await userEvent.type(screen.getByLabelText("Your role"), "  Head of sales ");
    await userEvent.type(screen.getByLabelText("Time zone"), "Europe/Warsaw");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save).toHaveBeenCalledWith({
      job_title: "Head of sales",
      about: null,
      time_zone: "Europe/Warsaw",
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
    await userEvent.clear(screen.getByLabelText("Time zone"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(save).toHaveBeenCalledWith({ job_title: null, about: null, time_zone: null });
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
});
