import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { YourSuggestions } from "./your-suggestions";
import type { Suggestion } from "@/lib/suggestions-api";

/**
 * The person's side of the nightly look (#2301): switching it off for
 * themselves, and seeing - and bringing back - what it proposed.
 */

const state = vi.hoisted(() => ({
  optedOut: false,
  orgOn: true as boolean | undefined,
  history: [] as Suggestion[],
  saveOptOut: vi.fn(),
  restore: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    activeOrg: state.orgOn === undefined ? null : { proactive_enabled: state.orgOn },
  }),
}));
vi.mock("@/hooks/use-account-profile", () => ({ useSaveProactiveOptOut: () => state.saveOptOut }));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestionHistory: () => ({
    history: state.history,
    isLoading: false,
    restore: state.restore,
  }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (store: { user: { proactive_opt_out: boolean } }) => unknown) =>
    pick({ user: { proactive_opt_out: state.optedOut } }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

function suggestion(id: string, status: Suggestion["status"], detail: string | null = null) {
  return {
    id,
    kind: "routine",
    status,
    title: `Title ${id}`,
    detail,
    payload: {},
    created_at: "2026-10-22T05:00:00Z",
  } satisfies Suggestion;
}

beforeEach(() => {
  state.optedOut = false;
  state.orgOn = true;
  state.history = [];
  state.saveOptOut.mockReset().mockResolvedValue(undefined);
  state.restore.mockReset().mockResolvedValue(undefined);
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("YourSuggestions", () => {
  it("lets a person leave themselves out, and back in", async () => {
    render(<YourSuggestions />);
    const mine = screen.getByRole("switch", { name: "Nightly suggestions for me" });
    expect(mine).toBeChecked();

    await userEvent.click(mine);

    expect(state.saveOptOut).toHaveBeenCalledWith(true);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions are off for you"),
    );
  });

  it("lets one who opted out back in", async () => {
    state.optedOut = true;
    render(<YourSuggestions />);

    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions for me" }));

    expect(state.saveOptOut).toHaveBeenCalledWith(false);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions are on for you"),
    );
  });

  it("says when the organization has none made at all", () => {
    state.orgOn = false;
    render(<YourSuggestions />);
    expect(screen.getByText(/organization has nightly suggestions off/)).toBeInTheDocument();
  });

  it("says nothing of the organization it knows nothing about", () => {
    state.orgOn = undefined;
    render(<YourSuggestions />);
    expect(screen.queryByText(/organization has nightly suggestions off/)).toBeNull();
  });

  it("lists what was proposed and brings a declined one back", async () => {
    state.history = [
      suggestion("a", "open", "Every Monday"),
      suggestion("b", "accepted"),
      suggestion("c", "dismissed"),
    ];
    render(<YourSuggestions />);

    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).getByText("Waiting")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Every Monday")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Taken")).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole("button")).toBeNull();

    await userEvent.click(within(rows[2]!).getByRole("button", { name: "Bring back" }));

    expect(state.restore).toHaveBeenCalledWith("c");
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Back among your suggestions"));
  });

  it("says when nothing was proposed yet, and a failed answer out loud", async () => {
    state.saveOptOut.mockRejectedValue(new Error("down"));
    render(<YourSuggestions />);
    expect(screen.getByText("Nothing proposed yet.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions for me" }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
