import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent } from "@/components/ui";
import { DesktopSetupMenuItem, OPEN_DESKTOP_SETUP } from "./desktop-setup-menu-item";
import { MAC_MAIN } from "./fixtures";
const env = vi.hoisted(() => ({ shell: null as unknown }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
it("omits the desktop setup action in browsers and auxiliary windows", () => {
  const view = render(<DesktopSetupMenuItem />);
  expect(view.container).toBeEmptyDOMElement();
  env.shell = { ...MAC_MAIN, window: "quick-ask" };
  view.rerender(<DesktopSetupMenuItem />);
  expect(view.container).toBeEmptyDOMElement();
});

it("opens the connection checklist from the main window's account menu", async () => {
  env.shell = MAC_MAIN;
  const opened = vi.fn();
  window.addEventListener(OPEN_DESKTOP_SETUP, opened);
  const view = render(
    <DropdownMenu>
      <DropdownMenuTrigger>Account</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DesktopSetupMenuItem />
      </DropdownMenuContent>
    </DropdownMenu>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Account" }));
  await userEvent.click(screen.getByRole("menuitem"));
  expect(opened).toHaveBeenCalledOnce();
  window.removeEventListener(OPEN_DESKTOP_SETUP, opened);
  view.unmount();
});
