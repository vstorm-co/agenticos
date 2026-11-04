import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { ShellInfo } from "@/lib/desktop/shell";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui";
import { ServerSwitch } from "./server-switch";
import { MAC_MAIN } from "./fixtures";

const env = vi.hoisted(() => ({
  shell: null as ShellInfo | null,
  pending: false,
  change: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useChangeServer: () => ({ mutate: env.change, isPending: env.pending }),
}));

beforeEach(() => {
  env.shell = MAC_MAIN;
  env.pending = false;
  env.change.mockClear();
});

function renderSwitch() {
  return render(
    <DropdownMenu open>
      <DropdownMenuTrigger>Account</DropdownMenuTrigger>
      <DropdownMenuContent>
        <ServerSwitch />
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

it("opens the native picker from an account menu item", async () => {
  renderSwitch();
  expect(env.change).not.toHaveBeenCalled();
  await userEvent.click(await screen.findByRole("menuitem", { name: "Change server…" }));
  expect(env.change).toHaveBeenCalledOnce();
});

it("prevents duplicate requests while the native picker opens", async () => {
  env.pending = true;
  renderSwitch();
  const button = screen.getByRole("menuitem", { name: "Change server…" });
  expect(button).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(button);
  expect(env.change).not.toHaveBeenCalled();
});

it.each<ShellInfo | null>([
  null,
  { ...MAC_MAIN, platform: "ios" },
  { ...MAC_MAIN, platform: "android" },
  { ...MAC_MAIN, window: "blobby" },
  { ...MAC_MAIN, window: "quick-ask" },
])("offers the picker only in the main desktop window: %j", (shell) => {
  env.shell = shell;
  renderSwitch();
  expect(screen.queryByRole("menuitem", { name: "Change server…" })).not.toBeInTheDocument();
});
