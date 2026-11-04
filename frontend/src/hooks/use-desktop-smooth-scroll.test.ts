import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useDesktopSmoothScroll } from "./use-desktop-smooth-scroll";
const motion = vi.hoisted(() => ({ reduced: false }));
const dispose = vi.hoisted(() => vi.fn());
const install = vi.hoisted(() => vi.fn(() => dispose));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motion.reduced }));
vi.mock("@/lib/desktop/smooth-scroll", () => ({ smoothDesktopWheel: install }));
beforeEach(() => {
  vi.clearAllMocks();
  motion.reduced = false;
  document.body.innerHTML = '<main id="main"></main>';
});
it("installs only on the desktop scrollport and disposes when motion is reduced", () => {
  const view = renderHook(() => useDesktopSmoothScroll(true));
  expect(install).toHaveBeenCalledWith(document.getElementById("main"));
  motion.reduced = true;
  view.rerender();
  expect(dispose).toHaveBeenCalledOnce();
  view.unmount();
});
it.each([false, true])("does not install without an enabled scrollport (%s)", (enabled) => {
  document.body.replaceChildren();
  renderHook(() => useDesktopSmoothScroll(enabled));
  expect(install).not.toHaveBeenCalled();
});
