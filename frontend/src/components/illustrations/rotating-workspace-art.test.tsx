import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RotatingWorkspaceArt } from "./rotating-workspace-art";

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => preference.reduced }));
vi.mock("./workspace-atmosphere", () => ({
  WorkspaceAtmosphere: ({ scene }: { scene: string }) => <svg data-scene={scene} />,
}));

beforeEach(() => {
  vi.useFakeTimers();
  preference.reduced = false;
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function activeScene(container: HTMLElement) {
  return container.querySelector('[data-active="true"] svg')?.getAttribute("data-scene");
}

it("cycles through distinct illustrations and releases its timer on unmount", () => {
  const view = render(<RotatingWorkspaceArt />);
  expect(activeScene(view.container)).toBe("landscape");
  act(() => vi.advanceTimersByTime(18000));
  expect(activeScene(view.container)).toBe("orbit");
  act(() => vi.advanceTimersByTime(18000));
  expect(activeScene(view.container)).toBe("contours");
  act(() => vi.advanceTimersByTime(18000));
  expect(activeScene(view.container)).toBe("landscape");
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("lets the reader stop and resume the rotation", () => {
  const view = render(<RotatingWorkspaceArt />);
  fireEvent.click(screen.getByRole("button", { name: "Pause illustrations" }));
  act(() => vi.advanceTimersByTime(54000));
  expect(activeScene(view.container)).toBe("landscape");
  fireEvent.click(screen.getByRole("button", { name: "Resume illustrations" }));
  act(() => vi.advanceTimersByTime(18000));
  expect(activeScene(view.container)).toBe("orbit");
});
it("keeps the artwork static under reduced motion", () => {
  preference.reduced = true;
  const view = render(<RotatingWorkspaceArt />);
  act(() => vi.advanceTimersByTime(54000));
  expect(activeScene(view.container)).toBe("landscape");
  expect(screen.queryByRole("button")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});
it("does not cycle in a hidden tab", () => {
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  const view = render(<RotatingWorkspaceArt />);
  act(() => vi.advanceTimersByTime(54000));
  expect(activeScene(view.container)).toBe("landscape");
});
