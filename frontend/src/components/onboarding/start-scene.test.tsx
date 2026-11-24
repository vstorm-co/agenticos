import { useRef, useState } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMotionStore } from "@/stores/motion-store";
import { useStartTransition } from "./start-experience";

const cancel = vi.fn();
const animate = vi.fn<HTMLElement["animate"]>(() => new Animation());
const originalAnimate = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate");
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

function Scene({ enabled = true }: { enabled?: boolean }) {
  const scene = useRef<HTMLDivElement>(null);
  const transition = useStartTransition(scene, enabled);
  const [step, setStep] = useState("profile");
  return (
    <>
      <div ref={scene} data-testid="scene" data-step={step}>
        <input aria-label="Unsaved profile" defaultValue="Draft" />
      </div>
      <button
        onClick={() => {
          transition("forward");
          setStep("tools");
        }}
      >
        Next
      </button>
      <button
        onClick={() => {
          transition("back");
          setStep("profile");
        }}
      >
        Back
      </button>
    </>
  );
}

beforeEach(() => {
  useMotionStore.setState({ motion: "full" });
  document.documentElement.style.setProperty("--duration-base", "220ms");
  document.documentElement.style.setProperty("--ease-out", "cubic-bezier(0.22, 1, 0.36, 1)");
  vi.stubGlobal(
    "Animation",
    class {
      cancel = cancel;
    },
  );
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate });
  vi.clearAllMocks();
});
afterEach(() => {
  if (originalAnimate) Object.defineProperty(HTMLElement.prototype, "animate", originalAnimate);
  else Reflect.deleteProperty(HTMLElement.prototype, "animate");
  document.documentElement.style.removeProperty("--duration-base");
  document.documentElement.style.removeProperty("--ease-out");
  useMotionStore.setState({ motion: "system" });
  vi.unstubAllGlobals();
});

it("keeps initial and restored scenes still, then animates an explicit step without replacing its draft", async () => {
  render(<Scene />);
  expect(animate).not.toHaveBeenCalled();
  const input = screen.getByRole("textbox", { name: "Unsaved profile" });
  await userEvent.type(input, " stays");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(animate).toHaveBeenCalledWith(
    [
      { opacity: 0, transform: "translateX(24px)" },
      { opacity: 1, transform: "translateX(0)" },
    ],
    { duration: 220, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
  );
  expect(screen.getByTestId("scene")).toHaveAttribute("data-step", "tools");
  expect(screen.getByRole("textbox", { name: "Unsaved profile" })).toBe(input);
  expect(input).toHaveValue("Draft stays");
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(cancel).toHaveBeenCalledOnce();
  expect(animate).toHaveBeenLastCalledWith(
    [
      { opacity: 0, transform: "translateX(-24px)" },
      { opacity: 1, transform: "translateX(0)" },
    ],
    expect.objectContaining({ duration: 220 }),
  );
});

it("cancels an in-flight transition when motion is reduced and leaves navigation usable", async () => {
  render(<Scene />);
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(animate).toHaveBeenCalledOnce();
  act(() => useMotionStore.getState().setMotion("reduce"));
  expect(cancel).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(animate).toHaveBeenCalledOnce();
  expect(screen.getByTestId("scene")).toHaveAttribute("data-step", "profile");
});

it("uses the explicit Full preference even when the OS asks for reduced motion", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const view = render(<Scene />);
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(animate).toHaveBeenCalledOnce();
  view.unmount();
  expect(cancel).toHaveBeenCalledOnce();
});

it("keeps preview variants functional without adding Studio's scene motion", async () => {
  render(<Scene enabled={false} />);
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(animate).not.toHaveBeenCalled();
  expect(screen.getByTestId("scene")).toHaveAttribute("data-step", "tools");
});
