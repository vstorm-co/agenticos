import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
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

it("lets an open menu consume Escape before leaving the workspace", async () => {
  function Example() {
    const { ref, expanded, toggle } = useWorkspaceFullscreen();
    return (
      <div ref={ref} data-expanded={expanded}>
        <button onClick={toggle}>Expand</button>
        <div role="menu" data-state="open">
          Menu
        </div>
      </div>
    );
  }
  render(<Example />);
  await userEvent.click(screen.getByRole("button", { name: "Expand" }));
  const workspace = screen.getByRole("button", { name: "Expand" }).parentElement;
  fireEvent.keyDown(window, { key: "Escape" });
  expect(workspace).toHaveAttribute("data-expanded", "true");
  screen.getByRole("menu").remove();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(workspace).toHaveAttribute("data-expanded", "false");
});

it("stays expanded for any other key and for an Escape something else already handled", async () => {
  function Example() {
    const { ref, expanded, toggle } = useWorkspaceFullscreen();
    return (
      <div ref={ref} data-expanded={expanded}>
        <button onClick={toggle}>Expand</button>
      </div>
    );
  }
  const claim = (event: KeyboardEvent) => event.preventDefault();
  window.addEventListener("keydown", claim);
  render(<Example />);
  await userEvent.click(screen.getByRole("button", { name: "Expand" }));
  const shell = screen.getByRole("button", { name: "Expand" }).parentElement;

  fireEvent.keyDown(window, { key: "Enter" });
  expect(shell).toHaveAttribute("data-expanded", "true");

  try {
    fireEvent.keyDown(window, { key: "Escape", cancelable: true });
    expect(shell).toHaveAttribute("data-expanded", "true");
  } finally {
    window.removeEventListener("keydown", claim);
  }

  fireEvent.keyDown(window, { key: "Escape" });
  expect(shell).toHaveAttribute("data-expanded", "false");
});

it("restores the desktop shell after expanding on mobile without losing the draft", async () => {
  const query = Object.assign(new EventTarget(), {
    matches: false,
    media: "(min-width: 768px)",
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
  });
  const media = vi.spyOn(window, "matchMedia").mockReturnValue(query);
  function Example() {
    const { ref, expanded, toggle } = useWorkspaceFullscreen();
    return (
      <div ref={ref} data-expanded={expanded}>
        <input aria-label="Mobile draft" />
        <button onClick={toggle}>Expand mobile</button>
      </div>
    );
  }
  try {
    render(
      <div>
        <button>Desktop navigation</button>
        <Example />
      </div>,
    );
    const navigation = screen.getByRole("button", { name: "Desktop navigation" });
    const draft = screen.getByRole("textbox", { name: "Mobile draft" });
    await userEvent.type(draft, "Keep my edits");
    await userEvent.click(screen.getByRole("button", { name: "Expand mobile" }));
    expect(navigation.inert).toBe(true);
    query.matches = true;
    act(() => query.dispatchEvent(new Event("change")));
    expect(navigation.inert).toBe(false);
    expect(draft).toHaveValue("Keep my edits");
    expect(draft.parentElement).toHaveAttribute("data-expanded", "false");
  } finally {
    media.mockRestore();
  }
});
