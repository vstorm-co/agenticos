import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProbeTestButton, WhyDisabled } from "./probe-test-button";
import { Button } from "@/components/ui/button";

describe("ProbeTestButton", () => {
  it("offers the test while one is still owed", async () => {
    const onClick = vi.fn();
    render(<ProbeTestButton status="idle" disabled={false} onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("says the settings passed once they did", () => {
    render(<ProbeTestButton status="passed" disabled={false} onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Tested" })).toBeEnabled();
  });

  it("cannot be pressed again while a test is running", () => {
    render(<ProbeTestButton status="testing" disabled={false} onClick={vi.fn()} />);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

describe("WhyDisabled", () => {
  it("says why a disabled button is disabled on hover", async () => {
    render(
      <WhyDisabled reason="Run the test first.">
        <Button disabled>Save</Button>
      </WhyDisabled>,
    );
    await userEvent.hover(screen.getByRole("button", { name: "Save" }).parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Run the test first.");
  });

  it("leaves a button with no reason alone", () => {
    render(
      <WhyDisabled reason={null}>
        <Button>Save</Button>
      </WhyDisabled>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(screen.getByRole("button", { name: "Save" }).parentElement?.tagName).not.toBe("SPAN");
  });
});
