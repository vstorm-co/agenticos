import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMotionStore } from "@/stores/motion-store";
import { StartTypedMessage } from "./start-typed-message";
beforeEach(() => {
  useMotionStore.setState({ motion: "system" });
  vi.useFakeTimers();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    setTimeout(() => callback(performance.now()), 16),
  );
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
  delete document.documentElement.dataset.motion;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.motion;
});
it("keeps a complete accessible message while revealing its visual copy", () => {
  const { container } = render(<StartTypedMessage message="A full message for the user" />);
  const visual = container.querySelector('[aria-hidden="true"]');
  expect(visual).toHaveTextContent("");
  expect(container.firstElementChild?.firstElementChild).toHaveTextContent(
    "A full message for the user",
  );
  act(() => vi.advanceTimersByTime(1500));
  expect(visual).toHaveTextContent("A full message for the user");
});
it("ends in the full state under the app's reduced-motion setting", () => {
  useMotionStore.setState({ motion: "reduce" });
  const { container } = render(<StartTypedMessage message="Always readable" />);
  act(() => vi.advanceTimersByTime(32));
  expect(container.querySelector('[aria-hidden="true"]')).toHaveTextContent("Always readable");
});
it("cancels pending frames on unmount", () => {
  const { unmount } = render(<StartTypedMessage message="Hello" />);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("respects explicit Full when the operating system asks for reduced motion", () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  useMotionStore.setState({ motion: "full" });
  const { container } = render(<StartTypedMessage message="An intentional reveal" />);
  const visual = container.querySelector('[aria-hidden="true"]');
  act(() => vi.advanceTimersByTime(32));
  expect(visual?.textContent?.length).toBeLessThan("An intentional reveal".length);
  act(() => vi.advanceTimersByTime(1500));
  expect(visual).toHaveTextContent("An intentional reveal");
});
