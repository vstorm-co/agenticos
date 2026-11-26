import { createRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NativeDisclosure } from "./native-disclosure";

describe("NativeDisclosure", () => {
  it("retains native toggling and a draft without remounting content", async () => {
    const toggle = vi.fn();
    render(
      <NativeDisclosure onToggle={toggle}>
        <summary>More details</summary>
        <input aria-label="Draft" defaultValue="Original" />
      </NativeDisclosure>,
    );
    const summary = screen.getByText("More details");
    const input = screen.getByLabelText("Draft");
    expect(input).not.toBeVisible();
    await userEvent.click(summary);
    await userEvent.type(input, " changed");
    await userEvent.click(summary);
    expect(input).not.toBeVisible();
    await userEvent.click(summary);
    expect(screen.getByLabelText("Draft")).toBe(input);
    expect(input).toHaveValue("Original changed");
    await waitFor(() => expect(toggle).toHaveBeenCalled());
  });

  it("forwards its native ref, attributes and controlled open state", () => {
    const ref = createRef<HTMLDetailsElement>();
    const view = render(
      <NativeDisclosure ref={ref} open id="details">
        <summary>Details</summary>
        <p>Content</p>
      </NativeDisclosure>,
    );
    expect(ref.current).toBeInstanceOf(HTMLDetailsElement);
    expect(ref.current).toHaveAttribute("id", "details");
    expect(screen.getByText("Content")).toBeVisible();
    view.rerender(
      <NativeDisclosure ref={ref} open={false} id="details">
        <summary>Details</summary>
        <p>Content</p>
      </NativeDisclosure>,
    );
    expect(screen.getByText("Content")).not.toBeVisible();
  });
});
