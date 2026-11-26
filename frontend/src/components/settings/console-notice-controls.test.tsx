import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ConsoleNoticeControls } from "./console-notice-controls";

it("lets an administrator disable a product prompt", async () => {
  const change = vi.fn();
  render(
    <ConsoleNoticeControls value={{}} disabled={false} mode="availability" onChange={change} />,
  );
  await userEvent.click(screen.getByRole("switch", { name: "Desktop app invitation" }));
  expect(change).toHaveBeenCalledWith({ desktop_install_prompt: false });
});
it("keeps personal choices beneath the organization ceiling", async () => {
  const change = vi.fn();
  render(
    <ConsoleNoticeControls
      value={{}}
      ceiling={{ desktop_install_prompt: false }}
      disabled={false}
      mode="preference"
      onChange={change}
    />,
  );
  expect(screen.getByRole("combobox", { name: "Desktop app invitation" })).toBeDisabled();
  await userEvent.click(screen.getByRole("combobox", { name: "Product announcements" }));
  await userEvent.click(screen.getByRole("option", { name: "Hide" }));
  expect(change).toHaveBeenCalledWith({ product_notices: false });
});

it("allows a personal choice to return to inheritance", async () => {
  const change = vi.fn();
  const view = render(
    <ConsoleNoticeControls
      value={{ product_notices: false }}
      disabled={false}
      mode="preference"
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Product announcements" }));
  await userEvent.click(screen.getByRole("option", { name: "Show" }));
  expect(change).toHaveBeenLastCalledWith({ product_notices: true });
  view.rerender(
    <ConsoleNoticeControls
      value={{ product_notices: true }}
      disabled={false}
      mode="preference"
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Product announcements" }));
  await userEvent.click(screen.getByRole("option", { name: "Inherit (shown)" }));
  expect(change).toHaveBeenLastCalledWith({ product_notices: null });
});
