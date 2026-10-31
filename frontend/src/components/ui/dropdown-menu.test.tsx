import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./dropdown-menu";

function menu(select = vi.fn()) {
  render(
    <DropdownMenu>
      <DropdownMenuTrigger>Options</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem onSelect={select}>Duplicate</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
  return screen.getByRole("button", { name: "Options" });
}
function touchDown(target: Element) {
  const event = new Event("pointerdown", { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    pointerType: { value: "touch" },
    button: { value: 0 },
    ctrlKey: { value: false },
  });
  fireEvent(target, event);
}
it("opens after touch release, so the opening gesture cannot select a menu item", async () => {
  const select = vi.fn();
  const trigger = menu(select);
  touchDown(trigger);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  fireEvent.pointerUp(trigger);
  fireEvent.click(trigger);
  expect(await screen.findByRole("menu")).toBeInTheDocument();
  expect(select).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
  expect(select).toHaveBeenCalledTimes(1);
});
it("retains mouse, keyboard and Escape behavior", async () => {
  const trigger = menu();
  await userEvent.click(trigger);
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  trigger.focus();
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("menu")).toBeInTheDocument();
});
it("does not open after a cancelled gesture", () => {
  const trigger = menu();
  touchDown(trigger);
  fireEvent.pointerCancel(trigger);
  fireEvent.click(trigger);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});
it("preserves controlled and initially-open menus", async () => {
  function Controlled() {
    const [open, setOpen] = useState(true);
    return (
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger>Controlled</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Item</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }
  render(<Controlled />);
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("preserves default-open state and caller cancellation of touch opening", async () => {
  const view = render(
    <DropdownMenu defaultOpen>
      <DropdownMenuTrigger>Default</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem>Item</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  view.unmount();
  render(
    <DropdownMenu>
      <DropdownMenuTrigger onPointerDown={(event) => event.preventDefault()}>
        Blocked
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem>Item</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
  const trigger = screen.getByRole("button", { name: "Blocked" });
  touchDown(trigger);
  fireEvent.click(trigger);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});
