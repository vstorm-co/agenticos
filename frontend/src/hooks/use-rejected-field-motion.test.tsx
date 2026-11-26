import { render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useRejectedFieldMotion } from "./use-rejected-field-motion";

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => preference.reduced }));
const cancel = vi.fn();
const animate = vi.fn(() => ({ cancel }));
const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate");

function Field({ attempt }: { attempt: number }) {
  const ref = useRejectedFieldMotion(attempt);
  return <input aria-label="Password" ref={ref} defaultValue="retained" />;
}

beforeEach(() => {
  preference.reduced = false;
  vi.clearAllMocks();
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate });
});
afterEach(() => {
  if (original) Object.defineProperty(HTMLElement.prototype, "animate", original);
  else Reflect.deleteProperty(HTMLElement.prototype, "animate");
});

it("repeats feedback for each refusal without remounting or clearing the field", () => {
  const { rerender, unmount } = render(<Field attempt={0} />);
  const input = screen.getByRole("textbox");
  input.focus();
  expect(animate).not.toHaveBeenCalled();
  rerender(<Field attempt={1} />);
  expect(animate).toHaveBeenCalledWith(expect.any(Array), { duration: 360, easing: "ease-out" });
  rerender(<Field attempt={2} />);
  expect(animate).toHaveBeenCalledTimes(2);
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("retained");
  expect(input).toHaveFocus();
  unmount();
  expect(cancel).toHaveBeenCalledTimes(2);
});

it("stops motion when the reader switches to reduced motion", () => {
  const { rerender } = render(<Field attempt={1} />);
  preference.reduced = true;
  rerender(<Field attempt={2} />);
  expect(animate).toHaveBeenCalledTimes(1);
  expect(cancel).toHaveBeenCalledTimes(1);
});

it("works without a mounted field or the Web Animations API", () => {
  renderHook(() => useRejectedFieldMotion(1));
  Reflect.deleteProperty(HTMLElement.prototype, "animate");
  render(<Field attempt={1} />);
  expect(animate).not.toHaveBeenCalled();
});
