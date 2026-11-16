import { renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { useWideScreen } from "./use-wide-screen";

function Probe() {
  return useWideScreen() ? "wide" : "narrow";
}

it("follows the md breakpoint and stops listening when unmounted", () => {
  const add = vi.fn();
  const remove = vi.fn();
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: true,
        media: query,
        addEventListener: add,
        removeEventListener: remove,
      }) as unknown as MediaQueryList,
  );
  const { result, unmount } = renderHook(() => useWideScreen());
  expect(result.current).toBe(true);
  expect(add).toHaveBeenCalledWith("change", expect.any(Function));
  unmount();
  expect(remove).toHaveBeenCalledWith("change", add.mock.calls[0]![1]);
});

it("renders as a narrow screen on the server", () => {
  expect(renderToString(<Probe />)).toBe("narrow");
});
