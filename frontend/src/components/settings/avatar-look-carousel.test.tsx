import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { animate } from "motion/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMotionStore } from "@/stores/motion-store";
import { AvatarLookCarousel } from "./avatar-look-carousel";

vi.mock("@/components/ui/avatar-face", () => ({ AvatarFace: () => null }));
vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, animate: vi.fn(actual.animate) };
});
beforeEach(() => {
  useMotionStore.setState({ motion: "reduce" });
  vi.mocked(animate).mockClear();
});
afterEach(() => {
  vi.restoreAllMocks();
  useMotionStore.setState({ motion: "system" });
});

function viewport(container: HTMLElement) {
  const element = container.querySelector<HTMLElement>("[data-avatar-carousel-viewport]");
  if (!element) throw new Error("Missing interactive carousel viewport");
  return element;
}
function swipe(element: HTMLElement, dx: number, dy = 0) {
  const dispatch = (type: string, init: PointerEventInit, time: number) => {
    const event = new PointerEvent(type, { bubbles: true, pointerId: 1, ...init });
    Object.defineProperty(event, "timeStamp", { value: time });
    fireEvent(element, event);
  };
  dispatch("pointerdown", { button: 0, clientX: 200, clientY: 100 }, 0);
  dispatch("pointermove", { clientX: 200 + dx, clientY: 100 + dy }, 80);
  dispatch("pointerup", { clientX: 200 + dx, clientY: 100 + dy }, 200);
}

it("exposes the eleven real account looks and the confirmed choice without an initial announcement", () => {
  render(<AvatarLookCarousel seed="account" value={3} onChange={vi.fn()} />);
  expect(screen.getByRole("region", { name: "Choose your look" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Colour 3" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByRole("button", { name: /Colour \d|Automatic colour/ })).toHaveLength(11);
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  expect(screen.getByRole("button", { name: "Colour 3" })).toHaveAttribute("tabindex", "0");
  expect(screen.getByRole("button", { name: "Colour 4" })).toHaveAttribute("tabindex", "-1");
});
it("browses rapid next requests from their intended target without saving a colour", async () => {
  const change = vi.fn();
  const { container } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Next look" }));
  await userEvent.click(screen.getByRole("button", { name: "Next look" }));
  expect(viewport(container)).toHaveAttribute("data-motion", "instant");
  expect(container.querySelector('[data-current="true"] button')).toHaveAccessibleName("Colour 2");
  expect(screen.getByRole("button", { name: "Automatic colour" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: "Colour 2" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("status")).toHaveTextContent("Look 3 of 11");
  expect(change).not.toHaveBeenCalled();
});
it("snaps a pointer drag but suppresses its trailing click instead of choosing a colour", () => {
  const change = vi.fn();
  const { container } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  swipe(viewport(container), -120);
  expect(screen.getByRole("status")).toHaveTextContent("Look 2 of 11");
  fireEvent.click(screen.getByRole("button", { name: "Colour 1" }));
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Automatic colour" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
it("leaves vertical page gestures alone and keeps cancellation and other pointers from selecting", () => {
  const change = vi.fn();
  const { container } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  const element = viewport(container);
  swipe(element, -5, 100);
  expect(container.querySelector('[data-current="true"] button')).toHaveAccessibleName(
    "Automatic colour",
  );
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  fireEvent.pointerDown(element, { pointerId: 4, button: 0, clientX: 200, clientY: 100 });
  fireEvent.pointerMove(element, { pointerId: 5, clientX: 0, clientY: 100 });
  fireEvent.pointerCancel(element, { pointerId: 4 });
  expect(change).not.toHaveBeenCalled();
});
it("captures a press at its source and accepts another gesture after capture is lost", () => {
  const change = vi.fn();
  const { container } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  const card = screen.getByRole("button", { name: "Automatic colour" });
  const capture = vi.fn();
  Object.defineProperty(card, "setPointerCapture", { value: capture, configurable: true });
  fireEvent.pointerDown(card, { pointerId: 7, button: 0, clientX: 200, clientY: 100 });
  expect(capture).toHaveBeenCalledExactlyOnceWith(7);
  fireEvent.lostPointerCapture(card, { pointerId: 7 });
  swipe(viewport(container), -120);
  expect(screen.getByRole("status")).toHaveTextContent("Look 2 of 11");
  expect(change).not.toHaveBeenCalled();
});
it("browses a pointer-focused card but keeps a tap as the explicit choice", () => {
  const change = vi.fn();
  render(<AvatarLookCarousel seed="account" value={null} onChange={change} />);
  const card = screen.getByRole("button", { name: "Colour 3" });
  fireEvent.pointerDown(card, { pointerId: 3, button: 0, clientX: 200, clientY: 100 });
  fireEvent.focus(card);
  expect(change).not.toHaveBeenCalled();
  fireEvent.pointerUp(card, { pointerId: 3, clientX: 200, clientY: 100 });
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(card);
  expect(change).toHaveBeenCalledExactlyOnceWith(3);
});
it("moves keyboard focus with its preview and only chooses on Enter", async () => {
  const change = vi.fn();
  render(<AvatarLookCarousel seed="account" value={null} onChange={change} />);
  screen.getByRole("button", { name: "Automatic colour" }).focus();
  await userEvent.keyboard("{ArrowRight}{ArrowRight}");
  expect(screen.getByRole("button", { name: "Colour 2" })).toHaveFocus();
  expect(change).not.toHaveBeenCalled();
  await userEvent.keyboard("{End}");
  expect(screen.getByRole("button", { name: "Colour 10" })).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(change).toHaveBeenCalledExactlyOnceWith(10);
  await userEvent.keyboard("{Home}");
  expect(screen.getByRole("button", { name: "Automatic colour" })).toHaveFocus();
});
it("follows an externally confirmed colour without overwriting a profile", async () => {
  const change = vi.fn();
  const { container, rerender } = render(
    <AvatarLookCarousel seed="account" value={3} onChange={change} />,
  );
  rerender(<AvatarLookCarousel seed="account" value={7} onChange={change} />);
  await waitFor(() =>
    expect(container.querySelector('[data-current="true"] button')).toHaveAccessibleName(
      "Colour 7",
    ),
  );
  expect(screen.getByRole("button", { name: "Colour 7" })).toHaveAttribute("aria-pressed", "true");
  expect(change).not.toHaveBeenCalled();
});
it("retains finite-navigation focus and freezes every interaction during a save", async () => {
  const change = vi.fn();
  const { container, rerender } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  const previous = screen.getByRole("button", { name: "Previous look" });
  await userEvent.click(previous);
  expect(previous).toHaveFocus();
  expect(previous).toHaveAttribute("aria-disabled", "true");
  rerender(<AvatarLookCarousel seed="account" value={null} onChange={change} disabled />);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  swipe(viewport(container), -120);
  await userEvent.click(screen.getByRole("button", { name: "Colour 2" }));
  expect(change).not.toHaveBeenCalled();
  expect(container.querySelector('[data-current="true"] button')).toHaveAccessibleName(
    "Automatic colour",
  );
});
it("uses a real spring for Full and finishes its announcement before cleaning up", async () => {
  useMotionStore.setState({ motion: "full" });
  const cancel = vi.spyOn(window, "cancelAnimationFrame");
  const { container, unmount } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={vi.fn()} />,
  );
  expect(viewport(container)).toHaveAttribute("data-motion", "spring");
  await userEvent.click(screen.getByRole("button", { name: "Next look" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Look 2 of 11"));
  act(() => unmount());
  expect(cancel).toHaveBeenCalled();
});

it("finishes a chosen card's real spring while its colour is being saved", async () => {
  useMotionStore.setState({ motion: "full" });
  const change = vi.fn();
  const { rerender } = render(<AvatarLookCarousel seed="account" value={null} onChange={change} />);
  await userEvent.click(screen.getByRole("button", { name: "Colour 2" }));
  expect(change).toHaveBeenCalledExactlyOnceWith(2);
  const animation = vi.mocked(animate).mock.results.at(-1);
  if (!animation || animation.type !== "return") throw new Error("Expected the real choice spring");
  const stop = vi.spyOn(animation.value, "stop");
  rerender(<AvatarLookCarousel seed="account" value={null} onChange={change} disabled />);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  expect(stop).not.toHaveBeenCalled();
  rerender(<AvatarLookCarousel seed="account" value={2} onChange={change} disabled />);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Look 3 of 11"));
  expect(screen.getByRole("button", { name: "Colour 2" })).toHaveAttribute("aria-pressed", "true");
  expect(stop).not.toHaveBeenCalled();
});

it("releases an active pointer capture when saving starts without choosing the dragged preview", async () => {
  useMotionStore.setState({ motion: "full" });
  const change = vi.fn();
  const { container, rerender } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  const element = viewport(container);
  const release = vi.fn();
  Object.defineProperties(element, {
    setPointerCapture: { value: vi.fn(), configurable: true },
    hasPointerCapture: { value: () => true, configurable: true },
    releasePointerCapture: { value: release, configurable: true },
  });
  fireEvent.pointerDown(element, { pointerId: 9, button: 0, clientX: 200, clientY: 100 });
  fireEvent.pointerMove(element, { pointerId: 9, clientX: 80, clientY: 100 });
  expect(element).toHaveAttribute("data-dragging", "true");
  rerender(<AvatarLookCarousel seed="account" value={null} onChange={change} disabled />);
  expect(release).toHaveBeenCalledExactlyOnceWith(9);
  await waitFor(() => expect(element).not.toHaveAttribute("data-dragging"));
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Automatic colour" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
