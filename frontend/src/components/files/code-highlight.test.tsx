import { render, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HIGHLIGHT_UP_TO, toReact, useHighlighted } from "./code-highlight";

describe("colouring code", () => {
  it("is nothing until the grammars arrive, then the code in hljs classes", async () => {
    const { result } = renderHook(() => useHighlighted("return 1", "python"));

    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).not.toBeNull());
  });

  it("asks for nothing without a language, or for one with no grammar", async () => {
    const none = renderHook(() => useHighlighted("x", null));
    const unknown = renderHook(() => useHighlighted("x", "no-such-language"));

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(none.result.current).toBeNull();
    expect(unknown.result.current).toBeNull();
  });

  it("leaves text too long to colour without freezing the tab plain", async () => {
    const huge = renderHook(() => useHighlighted("x".repeat(HIGHLIGHT_UP_TO + 1), "python"));

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(huge.result.current).toBeNull();
  });

  it("never shows one file's colours over the next", async () => {
    const { result, rerender } = renderHook(({ text }) => useHighlighted(text, "python"), {
      initialProps: { text: "return 1" },
    });
    await waitFor(() => expect(result.current).not.toBeNull());

    rerender({ text: "return 2" });

    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).not.toBeNull());
  });

  it("drops an answer that lands after the viewer has gone", async () => {
    const { result, unmount } = renderHook(() => useHighlighted("return 3", "python"));
    unmount();

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current).toBeNull();
  });
});

describe("drawing a highlighted tree", () => {
  it("keeps spans and their text, and draws nothing for anything else", () => {
    const { container } = render(
      <pre>
        {toReact([
          {
            type: "element",
            tagName: "span",
            properties: { className: ["hljs-keyword"] },
            children: [{ type: "text", value: "def" }],
          },
          { type: "element", tagName: "span", properties: {}, children: [] },
          { type: "comment", value: "never shown" },
          { type: "text", value: "" },
        ])}
      </pre>,
    );

    expect(container.querySelector(".hljs-keyword")).toHaveTextContent("def");
    expect(container.querySelectorAll("span")).toHaveLength(2);
    expect(container).not.toHaveTextContent("never shown");
  });
});
