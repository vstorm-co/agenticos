import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CollapsibleBlock } from "./collapsible-block";

/**
 * The box a tool call's two halves sit in.
 *
 * What it has to get right is whose decision wins. The owner says what the block does
 * when the call's state changes - code open while it runs, closed once there is output
 * to read instead - and somebody who clicked it open has to keep it open through every
 * streaming delta that follows, which re-renders this subtree with the same props.
 */
describe("a block of text under its own header", () => {
  it("has no chevron when nothing may close it", () => {
    render(
      <CollapsibleBlock label="python">
        <pre>print(1)</pre>
      </CollapsibleBlock>,
    );

    expect(screen.queryByRole("button", { name: "python" })).toBeNull();
    expect(screen.getByText("print(1)")).toBeInTheDocument();
  });

  it("drops the header entirely for a block with nothing to head", () => {
    const { container } = render(
      <CollapsibleBlock label={null}>
        <pre />
      </CollapsibleBlock>,
    );

    expect(container.querySelector(".border-b")).toBeNull();
  });

  it("keeps the header of a closed block, which is all that is left of it", async () => {
    render(
      <CollapsibleBlock label="python" open>
        <pre>print(1)</pre>
      </CollapsibleBlock>,
    );

    await userEvent.click(screen.getByRole("button", { name: "python" }));

    expect(screen.queryByText("print(1)")).toBeNull();
    expect(screen.getByRole("button", { name: "python" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("survives a re-render that changes nothing, which is every streaming delta", async () => {
    const block = (
      <CollapsibleBlock label="python" open={false}>
        <pre>print(1)</pre>
      </CollapsibleBlock>
    );
    const { rerender } = render(block);

    await userEvent.click(screen.getByRole("button", { name: "python" }));
    rerender(block);

    expect(screen.getByText("print(1)")).toBeInTheDocument();
  });

  it("follows the owner when the owner changes its mind", () => {
    // The code that was worth watching while it ran, once its output has arrived.
    const { rerender } = render(
      <CollapsibleBlock label="python" open>
        <pre>print(1)</pre>
      </CollapsibleBlock>,
    );
    expect(screen.getByText("print(1)")).toBeInTheDocument();

    rerender(
      <CollapsibleBlock label="python" open={false}>
        <pre>print(1)</pre>
      </CollapsibleBlock>,
    );

    expect(screen.queryByText("print(1)")).toBeNull();
  });

  it("offers what is inside for copying, closed or open", () => {
    render(
      <CollapsibleBlock label="python" copyText="print(1)" open={false}>
        <pre>print(1)</pre>
      </CollapsibleBlock>,
    );

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("offers no copy for a block with nothing in it", () => {
    render(
      <CollapsibleBlock label="python" copyText="">
        <pre />
      </CollapsibleBlock>,
    );

    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });
});
