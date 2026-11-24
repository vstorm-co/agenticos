import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ModelSetupReply } from "./model-setup-reply";

const motion = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motion.reduced }));
vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p data-testid="answer">{content}</p>,
}));
vi.mock("./model-setup-card", () => ({
  ModelSetupCard: () => <div data-testid="setup-card" />,
}));
const text = "Connect a model and add your provider key. ".repeat(9);

beforeEach(() => {
  motion.reduced = false;
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
  vi.stubGlobal("matchMedia", () => ({ matches: motion.reduced }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("reveals even a long setup response gradually, then shows the card", () => {
  render(<ModelSetupReply text={text} agentId="starter" />);
  expect(screen.getByTestId("answer")).toBeEmptyDOMElement();
  expect(screen.queryByTestId("setup-card")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(160));
  const partial = screen.getByTestId("answer").textContent ?? "";
  expect(partial.length).toBeGreaterThan(0);
  expect(partial.length).toBeLessThan(text.length);
  act(() => vi.advanceTimersByTime(4000));
  expect(screen.getByTestId("answer")).toHaveTextContent(text.trim());
  expect(screen.getByTestId("setup-card")).toBeVisible();
});
it("shows the complete response and card immediately with reduced motion", () => {
  motion.reduced = true;
  render(<ModelSetupReply text={text} agentId="starter" />);
  expect(screen.getByTestId("answer")).toHaveTextContent(text.trim());
  expect(screen.getByTestId("setup-card")).toBeVisible();
});
it("cancels the reveal frame on unmount", () => {
  const cancel = vi.spyOn(window, "cancelAnimationFrame");
  const { unmount } = render(<ModelSetupReply text={text} />);
  unmount();
  expect(cancel).toHaveBeenCalled();
});
