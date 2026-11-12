import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SlashCommandsManager } from "./slash-commands-manager";

const state = vi.hoisted(() => ({ createCustom: vi.fn(), updateCustom: vi.fn() }));
vi.mock("@/hooks", () => ({
  BUILTIN_COMMAND_LIST: [],
  isBuiltinEnabled: vi.fn(),
  useSlashCommands: () => ({
    records: [],
    isLoading: false,
    error: null,
    ...state,
    refresh: vi.fn(),
    setBuiltinEnabled: vi.fn(),
    remove: vi.fn(),
  }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

beforeEach(() => vi.clearAllMocks());

describe("custom command identifiers", () => {
  it("normalizes a human name at submit even without blur", async () => {
    render(<SlashCommandsManager />);
    fireEvent.click(screen.getByRole("button", { name: "New command" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "/Daily Review" } });
    expect(screen.getByLabelText("Name")).toHaveValue("/Daily Review");
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Summarize today" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(state.createCustom).toHaveBeenCalledWith({
        name: "daily-review",
        prompt: "Summarize today",
      }),
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("preserves an unrepresentable name and prompt after refusal", async () => {
    render(<SlashCommandsManager />);
    fireEvent.click(screen.getByRole("button", { name: "New command" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "🤖" } });
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Keep my draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(state.createCustom).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Prompt")).toHaveValue("Keep my draft");
    expect(toast.error).toHaveBeenCalled();
  });
});
