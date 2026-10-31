import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { useWorkspaceFullscreen } from "./use-workspace-fullscreen";

it("expands without remounting edits, dismisses with Escape and restores the shell", async () => {
  function Example() {
    const { ref, expanded, toggle } = useWorkspaceFullscreen();
    return (
      <div ref={ref} data-expanded={expanded}>
        <input aria-label="Draft" defaultValue="" />
        <button onClick={toggle}>Expand</button>
      </div>
    );
  }
  render(
    <div>
      <button>Outside</button>
      <Example />
    </div>,
  );
  const outside = screen.getByRole("button", { name: "Outside" });
  const input = screen.getByRole("textbox", { name: "Draft" });
  await userEvent.type(input, "Unsaved text");
  await userEvent.click(screen.getByRole("button", { name: "Expand" }));
  expect(input).toBe(screen.getByRole("textbox", { name: "Draft" }));
  expect(input).toHaveValue("Unsaved text");
  expect(outside.inert).toBe(true);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(outside.inert).toBe(false);
  expect(input.parentElement).toHaveAttribute("data-expanded", "false");
});
