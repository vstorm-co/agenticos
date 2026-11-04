import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SWIPE_THRESHOLD, SwipeToDecide } from "./swipe-to-decide";

const haptic = vi.hoisted(() => vi.fn());
vi.mock("@/lib/mobile/haptics", () => ({ haptic }));

function row(props: Partial<Parameters<typeof SwipeToDecide>[0]> = {}) {
  const onApprove = vi.fn();
  const onReject = vi.fn();
  render(
    <SwipeToDecide
      onApprove={onApprove}
      onReject={onReject}
      approveLabel="Approve"
      rejectLabel="Reject"
      {...props}
    >
      <p>Send an email to the customer</p>
    </SwipeToDecide>,
  );
  const target = screen.getByText("Send an email to the customer").parentElement!;
  return { onApprove, onReject, target };
}

/** A finger from (0, 0) along the path given, lifted at its end. */
function swipe(target: Element, path: [number, number][], pointerType = "touch") {
  fireEvent.pointerDown(target, { pointerId: 1, pointerType, clientX: 0, clientY: 0 });
  for (const [x, y] of path) {
    fireEvent.pointerMove(target, { pointerId: 1, pointerType, clientX: x, clientY: y });
  }
  fireEvent.pointerUp(target, { pointerId: 1, pointerType });
}

beforeEach(() => {
  haptic.mockClear();
});

describe("SwipeToDecide", () => {
  it("approves on a swipe to the right past the point of no return", () => {
    const { onApprove, onReject, target } = row();
    swipe(target, [
      [20, 0],
      [SWIPE_THRESHOLD + 10, 2],
    ]);

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).not.toHaveBeenCalled();
    expect(haptic.mock.calls.map(([kind]) => kind)).toEqual(["threshold", "success"]);
  });

  it("rejects on a swipe to the left, and shows what it will do as it goes", () => {
    const { onApprove, onReject, target } = row();
    fireEvent.pointerDown(target, { pointerId: 1, pointerType: "touch", clientX: 0, clientY: 0 });
    fireEvent.pointerMove(target, { pointerId: 1, pointerType: "touch", clientX: -40, clientY: 0 });
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(target.style.transform).toBe("translateX(-40px)");
    fireEvent.pointerMove(target, {
      pointerId: 1,
      pointerType: "touch",
      clientX: -SWIPE_THRESHOLD - 5,
      clientY: 0,
    });
    fireEvent.pointerUp(target, { pointerId: 1, pointerType: "touch" });

    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
    expect(haptic).toHaveBeenLastCalledWith("warning");
    expect(target.style.transform).toBe("");
  });

  it("springs back short of the point, and says so with a tap only once it is passed", () => {
    const { onApprove, onReject, target } = row();
    swipe(target, [
      [20, 0],
      [SWIPE_THRESHOLD + 5, 0],
      [SWIPE_THRESHOLD - 30, 0],
    ]);

    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    expect(haptic.mock.calls.map(([kind]) => kind)).toEqual(["threshold"]);
  });

  it("leaves a finger moving down the page to scroll it", () => {
    const { onApprove, target } = row();
    swipe(target, [
      [4, 4],
      [10, 40],
      [SWIPE_THRESHOLD + 10, 60],
    ]);

    expect(onApprove).not.toHaveBeenCalled();
    expect(target.style.transform).toBe("");
  });

  it("ignores a mouse, another finger, and a row already deciding", () => {
    const mouse = row();
    swipe(mouse.target, [[SWIPE_THRESHOLD + 10, 0]], "mouse");
    expect(mouse.onApprove).not.toHaveBeenCalled();

    fireEvent.pointerDown(mouse.target, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 0,
      clientY: 0,
    });
    fireEvent.pointerMove(mouse.target, {
      pointerId: 2,
      pointerType: "touch",
      clientX: SWIPE_THRESHOLD + 10,
      clientY: 0,
    });
    fireEvent.pointerUp(mouse.target, { pointerId: 2, pointerType: "touch" });
    expect(mouse.onApprove).not.toHaveBeenCalled();
  });

  it("does nothing while a decision is settling", () => {
    const { onApprove, target } = row({ disabled: true });
    swipe(target, [[SWIPE_THRESHOLD + 10, 0]]);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("lets go when the system takes the touch", () => {
    const { onApprove, target } = row();
    fireEvent.pointerDown(target, { pointerId: 1, pointerType: "touch", clientX: 0, clientY: 0 });
    fireEvent.pointerMove(target, {
      pointerId: 1,
      pointerType: "touch",
      clientX: SWIPE_THRESHOLD + 10,
      clientY: 0,
    });
    fireEvent.pointerCancel(target, { pointerId: 1, pointerType: "touch" });
    fireEvent.pointerUp(target, { pointerId: 1, pointerType: "touch" });

    expect(onApprove).not.toHaveBeenCalled();
    expect(target.style.transform).toBe("");
  });

  it("does nothing on a tap", () => {
    const { onApprove, onReject, target } = row();
    swipe(target, [[2, 1]]);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });
});
