import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useOnline } from "./use-online";

function Online() {
  return <span>{useOnline() ? "online" : "offline"}</span>;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useOnline", () => {
  it("follows the browser's network as it comes and goes", () => {
    const onLine = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    const { result } = renderHook(() => useOnline());
    expect(result.current).toBe(true);

    onLine.mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current).toBe(false);

    onLine.mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current).toBe(true);
  });

  it("renders online on the server", () => {
    expect(renderToString(<Online />)).toContain("online");
  });
});
