import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { resetAccountAppearance } from "@/lib/account-appearance";
import { DEFAULT_APPEARANCE, type UserAppearance } from "@/lib/user-appearance";
import { saveUserAppearance } from "@/lib/user-appearance-api";
import { useAuthStore } from "@/stores/auth-store";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";
import type { User } from "@/types";
import { CanvasToolbar } from "./canvas-toolbar";

vi.mock("@/lib/user-appearance-api", () => ({ saveUserAppearance: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const alice = { id: "alice" } as User;
const changed = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(saveUserAppearance).mockReset();
  resetAccountAppearance();
  useAuthStore.setState({ user: alice, sessionOwnerId: alice.id });
  useWorkflowEditorStore.getState().seedGraph({
    entry_node_id: "",
    nodes: [],
    edges: [],
    bindings: [],
    scopes: [],
  });
  window.addEventListener("account-appearance-changed", changed);
});

afterEach(() => {
  cleanup();
  window.removeEventListener("account-appearance-changed", changed);
  useWorkflowEditorStore.getState().teardown();
  useAuthStore.setState({ user: null, sessionOwnerId: null });
  resetAccountAppearance();
});

function toolbar() {
  render(
    <CanvasToolbar catalog={[]} problems={[]} readOnly empty onAdd={vi.fn()} onTidy={vi.fn()} />,
  );
}

async function choosePlainSteps() {
  await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
  await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Show steps plainly" }));
}

it("keeps the saved node style until the account acknowledges a change", async () => {
  let finishSave!: (preferences: UserAppearance) => void;
  vi.mocked(saveUserAppearance).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishSave = resolve;
      }),
  );
  toolbar();
  await choosePlainSteps();
  expect(saveUserAppearance).toHaveBeenCalledWith({ workflow_nodes: "simple" });
  expect(useWorkflowNodeStyleStore.getState().style).toBe("colour");
  expect(changed).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
  expect(screen.getByRole("menuitemcheckbox", { name: "Show steps plainly" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );

  await act(async () => {
    finishSave({ ...DEFAULT_APPEARANCE, workflow_nodes: "simple" });
  });
  expect(useWorkflowNodeStyleStore.getState().style).toBe("simple");
  expect(changed).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("menuitemcheckbox", { name: "Show steps in colour" }),
  ).not.toHaveAttribute("aria-disabled", "true");
});

it("reports a refused save without changing the graph appearance and allows a retry", async () => {
  vi.mocked(saveUserAppearance)
    .mockRejectedValueOnce(new Error("appearance unavailable"))
    .mockResolvedValueOnce({ ...DEFAULT_APPEARANCE, workflow_nodes: "simple" });
  toolbar();
  await choosePlainSteps();
  await waitFor(() => expect(toast.error).toHaveBeenCalledOnce());
  expect(useWorkflowNodeStyleStore.getState().style).toBe("colour");
  expect(changed).not.toHaveBeenCalled();

  await choosePlainSteps();
  expect(saveUserAppearance).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(useWorkflowNodeStyleStore.getState().style).toBe("simple"));
  expect(changed).toHaveBeenCalledOnce();
});

it("does not adopt a previous session's late response after signing in again", async () => {
  let finishSave!: (preferences: UserAppearance) => void;
  vi.mocked(saveUserAppearance).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishSave = resolve;
      }),
  );
  toolbar();
  await choosePlainSteps();
  act(() => {
    resetAccountAppearance();
    useAuthStore.setState({ user: null });
    useAuthStore.setState({ user: alice });
  });
  await act(async () => {
    finishSave({ ...DEFAULT_APPEARANCE, workflow_nodes: "simple" });
  });
  expect(useWorkflowNodeStyleStore.getState().style).toBe("colour");
  expect(changed).not.toHaveBeenCalled();
  expect(toast.error).not.toHaveBeenCalled();
});
