import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import type { UserSlashCommandRecord } from "@/lib/slash-commands-api";
import userEvent from "@testing-library/user-event";
import { SlashCommandsManager } from "./slash-commands-manager";

const state = vi.hoisted(() => ({
  createCustom: vi.fn(),
  updateCustom: vi.fn(),
  remove: vi.fn(),
  records: [] as UserSlashCommandRecord[],
}));
vi.mock("@/hooks", () => ({
  BUILTIN_COMMAND_LIST: [],
  isBuiltinEnabled: vi.fn(),
  useSlashCommands: () => ({
    isLoading: false,
    error: null,
    ...state,
    refresh: vi.fn(),
    setBuiltinEnabled: vi.fn(),
  }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

beforeEach(() => {
  vi.clearAllMocks();
  state.records = [];
  state.createCustom.mockResolvedValue(undefined);
  state.updateCustom.mockResolvedValue(undefined);
  state.remove.mockResolvedValue(undefined);
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
});

function savedCommand(): UserSlashCommandRecord {
  return {
    id: "c1",
    name: "daily-review",
    prompt: "Review today.",
    is_enabled: true,
    created_at: "2026-11-12",
    updated_at: null,
  };
}

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

describe("command editing and removal", () => {
  it("keeps an edited draft on Stay and closes only after an explicit discard", async () => {
    state.records = [savedCommand()];
    render(<SlashCommandsManager />);
    await userEvent.click(screen.getByRole("button", { name: "Edit /daily-review" }));
    await userEvent.type(screen.getByLabelText("Prompt"), " Keep this addition.");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(useUnsavedChangesStore.getState().prompt).not.toBeNull();
    await act(() => useUnsavedChangesStore.getState().answer("stay"));
    expect(screen.getByLabelText("Prompt")).toHaveValue("Review today. Keep this addition.");
    await userEvent.keyboard("{Escape}");
    await act(() => useUnsavedChangesStore.getState().answer("discard"));
    expect(screen.queryByLabelText("Prompt")).not.toBeInTheDocument();
    expect(state.updateCustom).not.toHaveBeenCalled();
  });

  it("locks pending draft fields and dismissal, then restores editing after refusal", async () => {
    state.records = [savedCommand()];
    let rejectWrite: (error: Error) => void = () => {
      throw new Error("Write not started");
    };
    state.updateCustom.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectWrite = reject;
        }),
    );
    render(<SlashCommandsManager />);
    await userEvent.click(screen.getByRole("button", { name: "Edit /daily-review" }));
    await userEvent.type(screen.getByLabelText("Prompt"), " Saved addition.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByLabelText("Prompt")).toBeDisabled();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeVisible();
    await act(async () => rejectWrite(new Error("Controlled refusal")));
    await waitFor(() => expect(screen.getByLabelText("Prompt")).toBeEnabled());
    expect(screen.getByLabelText("Prompt")).toHaveValue("Review today. Saved addition.");
    expect(toast.error).toHaveBeenCalledWith("Controlled refusal");
  });

  it("keeps a refused guarded save in the editor", async () => {
    state.records = [savedCommand()];
    state.updateCustom.mockRejectedValueOnce(new Error("Controlled refusal"));
    render(<SlashCommandsManager />);
    await userEvent.click(screen.getByRole("button", { name: "Edit /daily-review" }));
    await userEvent.type(screen.getByLabelText("Prompt"), " Unsaved.");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(() => useUnsavedChangesStore.getState().answer("save"));
    expect(screen.getByLabelText("Prompt")).toHaveValue("Review today. Unsaved.");
    expect(state.updateCustom).toHaveBeenCalledWith(
      "c1",
      expect.objectContaining({ prompt: "Review today. Unsaved." }),
    );
  });

  it("confirms removal, keeps a refusal open and allows a retry", async () => {
    state.records = [savedCommand()];
    state.remove.mockRejectedValueOnce(new Error("Cannot remove"));
    render(<SlashCommandsManager />);
    await userEvent.click(screen.getByRole("button", { name: "Delete /daily-review" }));
    expect(state.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(state.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete /daily-review" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Cannot remove"));
    expect(screen.getByRole("dialog")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(state.remove).toHaveBeenCalledTimes(2);
  });

  it("blocks repeated toggles and conflicting edits until the write settles", async () => {
    state.records = [savedCommand()];
    let finish: () => void = () => {
      throw new Error("Write not started");
    };
    state.updateCustom.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = () => resolve(undefined);
        }),
    );
    render(<SlashCommandsManager />);
    const toggle = screen.getByRole("switch", { name: "Enable /daily-review" });
    await userEvent.click(toggle);
    expect(toggle).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit /daily-review" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete /daily-review" })).toBeDisabled();
    await userEvent.click(toggle);
    expect(state.updateCustom).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    expect(toggle).toBeEnabled();
  });
});
