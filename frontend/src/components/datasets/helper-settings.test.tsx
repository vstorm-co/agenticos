import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { HelperSettings } from "./helper-settings";
import type { Dataset, DatasetHelperSettings } from "@/types/datasets";
import { DEFAULT_SCORING } from "@/lib/scoring";
function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "d1",
    name: "Refunds",
    description: null,
    visibility: "org",
    owner_user_id: null,
    agent_id: null,
    latest_version: 1,
    case_count: 0,
    can_edit: true,
    can_run: true,
    run_needs: [],
    pending_proposals: 0,
    scoring: DEFAULT_SCORING,
    judge_name: null,
    stats: {
      with_reference: 0,
      with_counter_example: 0,
      with_tool_calls: 0,
      with_checks: 0,
      expectation_mix: [],
      by_source: { manual: 0, import: 0, conversation: 0, synthetic: 0 },
      top_tags: [],
    },
    created_at: "2026-11-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
const state = vi.hoisted(() => ({ save: vi.fn(), allowAdd: false }));
vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({ update: { mutateAsync: state.save, isPending: false } }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [], profilesStatus: "ready" }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowAdd }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    value,
    onChange,
    disabled,
    allowAdd,
  }: {
    value: string | null;
    onChange: (id: string) => void;
    disabled: boolean;
    allowAdd: boolean;
  }) => (
    <button disabled={disabled} onClick={() => onChange("new-model")} data-add={allowAdd}>
      {value ?? "Choose model"}
    </button>
  ),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";
const configured = () =>
  dataset({
    helper_settings: {
      generator: { model_profile_id: "old-model", instructions: "Draft cases." },
      improver: { model_profile_id: "improve-model", instructions: "Improve safely." },
    },
    helper_defaults: {
      generator: "Code generator instructions",
      improver: "Code improver instructions",
      judge: "Code judge instructions",
    },
  });
beforeEach(() => {
  vi.clearAllMocks();
  state.save.mockImplementation(
    async ({ helper_settings }: { helper_settings: Partial<DatasetHelperSettings> }) => ({
      ...configured(),
      helper_settings: { ...configured().helper_settings!, ...helper_settings },
    }),
  );
  state.allowAdd = false;
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
});
it("sends only the edited helper so another settings form cannot overwrite it", async () => {
  render(<HelperSettings dataset={configured()} kind="generator" />);
  await userEvent.click(screen.getByRole("button", { name: "old-model" }));
  await userEvent.clear(screen.getByRole("textbox", { name: "Instructions" }));
  await userEvent.type(
    screen.getByRole("textbox", { name: "Instructions" }),
    "Use actual policy examples.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.save).toHaveBeenCalledWith({
    helper_settings: {
      generator: { model_profile_id: "new-model", instructions: "Use actual policy examples." },
    },
  });
});
it("discards changes and preserves the draft when saving is refused", async () => {
  state.save.mockRejectedValue(new Error("Access changed"));
  render(<HelperSettings dataset={configured()} kind="improver" />);
  await userEvent.click(screen.getByRole("button", { name: "improve-model" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Access changed"));
  expect(screen.getByRole("button", { name: "new-model" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "improve-model" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "improve-model" }));
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(proceed).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "improve-model" })).toBeInTheDocument();
});
it("shows code defaults on demand to readers without offering edits", async () => {
  render(
    <HelperSettings
      dataset={dataset({ can_edit: false, helper_defaults: configured().helper_defaults })}
      kind="generator"
    />,
  );
  expect(screen.queryByRole("textbox", { name: "Instructions" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Instructions" }));
  expect(screen.getByRole("textbox", { name: "Instructions" })).toHaveValue(
    "Code generator instructions",
  );
  expect(screen.getByRole("textbox", { name: "Instructions" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Choose model" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
});

it("refreshes untouched settings and keeps actual unsaved instructions during a server update", async () => {
  const initial = configured();
  const { rerender } = render(<HelperSettings dataset={initial} kind="generator" />);
  const updated = {
    ...initial,
    helper_settings: {
      ...initial.helper_settings!,
      generator: { model_profile_id: "server-model", instructions: "New server instructions." },
    },
  };
  rerender(<HelperSettings dataset={updated} kind="generator" />);
  expect(screen.getByRole("button", { name: "server-model" })).toBeInTheDocument();
  const instructions = screen.getByRole("textbox", { name: "Instructions" });
  expect(instructions).toHaveValue("New server instructions.");
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  await userEvent.clear(instructions);
  await userEvent.type(instructions, "My unsaved instructions.");
  const next = {
    ...updated,
    helper_settings: {
      ...updated.helper_settings,
      generator: { ...updated.helper_settings.generator, instructions: "Another remote change." },
    },
  };
  rerender(<HelperSettings dataset={next} kind="generator" />);
  expect(instructions).toHaveValue("My unsaved instructions.");
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
});

it("shows the instructions normalized by the server after saving", async () => {
  const initial = configured();
  const saved = {
    ...initial,
    helper_settings: {
      ...initial.helper_settings!,
      generator: { model_profile_id: "old-model", instructions: "Normalized instructions." },
    },
  };
  state.save.mockResolvedValue(saved);
  const { rerender } = render(<HelperSettings dataset={initial} kind="generator" />);
  const instructions = screen.getByRole("textbox", { name: "Instructions" });
  await userEvent.clear(instructions);
  await userEvent.type(instructions, "  Normalized instructions.  ");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(instructions).toHaveValue("Normalized instructions."));
  rerender(<HelperSettings dataset={saved} kind="generator" />);
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
});
