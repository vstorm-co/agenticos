import { renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { useNarrowScreen } from "./use-narrow-screen";

function Probe() {
  return useNarrowScreen() ? "narrow" : "wide";
}

it("asks for a screen below the sm breakpoint and stops listening when unmounted", () => {
  const add = vi.fn();
  const remove = vi.fn();
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: query === "(max-width: 639px)",
        media: query,
        addEventListener: add,
        removeEventListener: remove,
      }) as unknown as MediaQueryList,
  );
  const { result, unmount } = renderHook(() => useNarrowScreen());
  expect(result.current).toBe(true);
  expect(add).toHaveBeenCalledWith("change", expect.any(Function));
  unmount();
  expect(remove).toHaveBeenCalledWith("change", add.mock.calls[0]![1]);
});

it("renders as a wide screen on the server", () => {
  expect(renderToString(<Probe />)).toBe("wide");
});
