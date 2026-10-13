import { renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { useMounted } from "./use-mounted";

function Probe() {
  return <span>{String(useMounted())}</span>;
}

describe("useMounted", () => {
  it("is false on the server, which is the whole point of it", () => {
    // Driven through a real server render rather than asserted at second hand:
    // `getServerSnapshot` is the branch that prevents the hydration mismatch,
    // and it is unreachable from jsdom - a browser-only test would leave the
    // one thing this hook exists for unproven.
    expect(renderToString(<Probe />)).toContain("false");
  });

  it("is true in the browser, one render later", () => {
    const { result } = renderHook(() => useMounted());

    expect(result.current).toBe(true);
  });

  it("stays true across a re-render, because it cannot change back", () => {
    const { result, rerender } = renderHook(() => useMounted());
    rerender();

    expect(result.current).toBe(true);
  });
});
