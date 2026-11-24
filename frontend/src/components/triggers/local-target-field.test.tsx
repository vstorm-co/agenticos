import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { LocalTargetField } from "./local-target-field";
import type { LocalTarget } from "@/lib/desktop/commands";

const native = vi.hoisted(() => ({
  available: true,
  supportsWrites: true,
  device: "device",
  pick: vi.fn(),
  grants: [] as unknown[],
}));
vi.mock("@/hooks/use-routine-local-work", () => ({
  useRoutineLocalWork: () => ({
    available: native.available,
    supportsWrites: native.supportsWrites,
    identity: { device_id: native.device },
    pick: { isPending: false, mutate: native.pick },
    grants: { data: native.grants },
  }),
}));
const target: LocalTarget = {
  folder: "/work",
  device_id: "device",
  mode: "workspace_write",
  routine_grant: "grant",
  operations: { read: true, write: true, execute: true },
};
beforeEach(() => {
  native.available = true;
  native.supportsWrites = true;
  native.device = "device";
  native.pick.mockReset();
  native.grants = [];
});
it("retains the receipt while reducing permissions and clears command access too", async () => {
  const onChange = vi.fn();
  render(<LocalTargetField value={target} onChange={onChange} visible />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Write" }));
  expect(onChange).toHaveBeenCalledWith({
    ...target,
    folder: "/work",
    device_id: "device",
    mode: "read_only",
    operations: { read: true, write: false, execute: false },
  });
});
it("command access includes write access while keeping the receipt for comparison", async () => {
  const onChange = vi.fn();
  render(
    <LocalTargetField
      value={{
        ...target,
        mode: "read_only",
        operations: { read: true, write: false, execute: false },
      }}
      onChange={onChange}
      visible
    />,
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "Run commands" }));
  expect(onChange).toHaveBeenCalledWith({
    ...target,
    folder: "/work",
    device_id: "device",
    mode: "workspace_write",
    operations: { read: true, write: true, execute: true },
  });
});
it("a remote target is visible but can only be cleared without native authority", async () => {
  native.available = false;
  const onChange = vi.fn();
  render(<LocalTargetField value={target} onChange={onChange} visible />);
  expect(screen.getByRole("checkbox", { name: "Write" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /Choose a folder/ })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: /sandbox/ }));
  expect(onChange).toHaveBeenCalledWith(null);
});
it("does not offer another computer's grant for editing here", () => {
  native.device = "different-device";
  render(<LocalTargetField value={target} onChange={vi.fn()} visible />);
  expect(screen.getByRole("checkbox", { name: "Run commands" })).toBeDisabled();
});
it("choosing a folder only previews a new read-only target", async () => {
  const onChange = vi.fn();
  native.pick.mockImplementation(
    (_value: undefined, options: { onSuccess: (folder: string | null) => void }) =>
      options.onSuccess("/new"),
  );
  render(<LocalTargetField value={target} onChange={onChange} visible />);
  await userEvent.click(screen.getByRole("button", { name: /Choose a folder/ }));
  expect(onChange).toHaveBeenCalledWith({
    folder: "/new",
    device_id: "device",
    mode: "read_only",
    operations: { read: true, write: false, execute: false },
  });
});
it("does not draw private folders for another routine's creator", () => {
  render(<LocalTargetField value={target} onChange={vi.fn()} visible={false} />);
  expect(screen.queryByText("/work")).toBeNull();
});

it("keeps write and command selection disabled on a read-only native sandbox", () => {
  native.supportsWrites = false;
  render(<LocalTargetField value={target} onChange={vi.fn()} visible />);
  expect(screen.getByRole("checkbox", { name: "Write" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Run commands" })).toBeDisabled();
});

it("offers the folder already allowed for every routine, without asking", async () => {
  native.grants = [
    {
      id: "all",
      routine_id: null,
      root: "/Users/person",
      operations: { read: true, write: true, execute: false },
    },
  ];
  const onChange = vi.fn();
  render(<LocalTargetField value={null} onChange={onChange} visible />);
  await userEvent.click(screen.getByRole("button", { name: "Use the allowed folder" }));
  expect(onChange).toHaveBeenCalledWith({
    folder: "/Users/person",
    device_id: "device",
    mode: "workspace_write",
    operations: { read: true, write: true, execute: false },
  });
});
