import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DisclosureContent } from "./disclosure-content";

describe("DisclosureContent", () => {
  it("mounts on first opening and preserves a draft through repeated closes", async () => {
    const mounted = vi.fn();
    function Draft() {
      mounted();
      return <input aria-label="Draft" defaultValue="Original" />;
    }
    const content = <Draft />;
    const { rerender } = render(<DisclosureContent open={false}>{content}</DisclosureContent>);
    expect(mounted).not.toHaveBeenCalled();
    rerender(<DisclosureContent open>{content}</DisclosureContent>);
    const input = screen.getByRole("textbox", { name: "Draft" });
    await userEvent.type(input, " changed");
    rerender(<DisclosureContent open={false}>{content}</DisclosureContent>);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(input.closest("[inert]")).toHaveAttribute("aria-hidden", "true");
    rerender(<DisclosureContent open>{content}</DisclosureContent>);
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("Original changed");
    expect(mounted).toHaveBeenCalledTimes(1);
  });

  it("registers closed form fields immediately when requested", () => {
    render(
      <DisclosureContent open={false} mountOnOpen={false}>
        <input name="budget" defaultValue="3" />
      </DisclosureContent>,
    );
    expect(document.querySelector('input[name="budget"]')).toHaveValue("3");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("returns keyboard focus to its trigger when content closes automatically", () => {
    const view = (open: boolean) => (
      <>
        <button id="trigger">Details</button>
        <DisclosureContent open={open} triggerId="trigger">
          <input aria-label="Details" />
        </DisclosureContent>
      </>
    );
    const { rerender } = render(view(true));
    screen.getByRole("textbox").focus();
    const focus = vi.spyOn(screen.getByRole("button"), "focus");
    rerender(view(false));
    expect(screen.getByRole("button")).toHaveFocus();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
  });

  it("does not steal focus from elsewhere, including a missing trigger", () => {
    const { rerender } = render(
      <DisclosureContent open triggerId="absent">
        <input aria-label="Draft" />
      </DisclosureContent>,
    );
    screen.getByRole("textbox").focus();
    rerender(
      <DisclosureContent open={false} triggerId="absent">
        <input aria-label="Draft" />
      </DisclosureContent>,
    );
    expect(document.activeElement).not.toHaveAttribute("id", "absent");
  });
});
