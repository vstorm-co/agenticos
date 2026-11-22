import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi, type Mock } from "vitest";
import { AvatarLookCarousel } from "./avatar-look-carousel";
vi.mock("@/components/ui/avatar-face", () => ({ AvatarFace: () => null }));
type ScrollCall = (options?: ScrollToOptions | number, y?: number) => void;
let scroll: Mock<ScrollCall>;
beforeEach(() => {
  scroll = vi.fn<ScrollCall>(function (this: HTMLElement, options) {
    this.scrollLeft = typeof options === "number" ? options : (options?.left ?? 0);
  });
  vi.spyOn(HTMLElement.prototype, "scrollTo").mockImplementation(scroll);
});
function geometry(container: HTMLElement) {
  const track = container.querySelector<HTMLDivElement>("section > div:nth-child(2)")!;
  Object.defineProperty(track, "clientWidth", { value: 320, configurable: true });
  Array.from(track.children).forEach((child, index) => {
    Object.defineProperty(child, "offsetLeft", { value: 104 + index * 124, configurable: true });
    Object.defineProperty(child, "offsetWidth", { value: 112, configurable: true });
  });
  return track;
}
it("shows the real account looks and marks selection with more than colour", () => {
  render(<AvatarLookCarousel seed="account" value={3} onChange={vi.fn()} />);
  expect(screen.getByRole("region", { name: "Choose your look" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Colour 3" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByRole("button", { name: /Colour \d|Automatic colour/ })).toHaveLength(11);
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});
it("browses from the pending target without saving and announces settled scroll", async () => {
  const change = vi.fn();
  const { container } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  const track = geometry(container);
  await waitFor(() => expect(scroll).toHaveBeenCalled());
  await userEvent.click(screen.getByRole("button", { name: "Next look" }));
  await userEvent.click(screen.getByRole("button", { name: "Next look" }));
  expect(scroll).toHaveBeenLastCalledWith({ left: 248, behavior: "auto" });
  expect(change).not.toHaveBeenCalled();
  fireEvent.scroll(track);
  fireEvent(track, new Event("scrollend"));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Look 3 of 11"));
});
it("changes only on explicit choice and follows the confirmed controlled value", async () => {
  const change = vi.fn();
  const { container, rerender } = render(
    <AvatarLookCarousel seed="account" value={null} onChange={change} />,
  );
  geometry(container);
  await userEvent.click(screen.getByRole("button", { name: "Colour 4" }));
  expect(change).toHaveBeenCalledExactlyOnceWith(4);
  expect(screen.getByRole("button", { name: "Automatic colour" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  rerender(<AvatarLookCarousel seed="account" value={4} onChange={change} />);
  expect(screen.getByRole("button", { name: "Colour 4" })).toHaveAttribute("aria-pressed", "true");
});
it("retains finite-navigation focus and disables all changes while a save is pending", async () => {
  const change = vi.fn();
  const { rerender } = render(<AvatarLookCarousel seed="account" value={null} onChange={change} />);
  const previous = screen.getByRole("button", { name: "Previous look" });
  await userEvent.click(previous);
  expect(previous).toHaveFocus();
  expect(previous).toHaveAttribute("aria-disabled", "true");
  rerender(<AvatarLookCarousel seed="account" value={null} onChange={change} disabled />);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Colour 2" }));
  expect(change).not.toHaveBeenCalled();
});
it("cleans up queued animation frames when removed", () => {
  const cancel = vi.spyOn(window, "cancelAnimationFrame");
  const { unmount } = render(<AvatarLookCarousel seed="account" value={null} onChange={vi.fn()} />);
  act(() => unmount());
  expect(cancel).toHaveBeenCalled();
});
