import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartModel } from "./start-model";

const prepare = vi.hoisted(() => ({ mutate: vi.fn(), error: null as unknown, isPending: false }));
vi.mock("@/hooks/use-start", () => ({ useStart: () => ({ prepare }) }));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [], profilesStatus: "success" }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    onChange,
    allowAdd,
  }: {
    onChange: (id: string) => void;
    allowAdd: boolean;
  }) => (
    <button onClick={() => onChange("shared-model")}>
      {allowAdd ? "Choose or add model" : "Choose existing model"}
    </button>
  ),
}));
beforeEach(() => {
  vi.clearAllMocks();
  prepare.error = null;
  prepare.isPending = false;
});
it("requires a deliberate model choice before preparing, then closes only on success", async () => {
  const prepared = vi.fn();
  render(<StartModel allowAdd={false} onPrepared={prepared} />);
  const button = screen.getByRole("button", { name: "Prepare a text assistant" });
  expect(button).toBeDisabled();
  expect(prepare.mutate).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Choose existing model" }));
  await userEvent.click(button);
  expect(prepare.mutate).toHaveBeenCalledExactlyOnceWith("shared-model", { onSuccess: prepared });
  expect(prepared).not.toHaveBeenCalled();
});
it("keeps publication errors visible for correction", () => {
  prepare.error = new Error("Publication failed");
  render(<StartModel allowAdd onPrepared={vi.fn()} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Publication failed");
  expect(screen.getByRole("button", { name: "Choose or add model" })).toBeVisible();
});
