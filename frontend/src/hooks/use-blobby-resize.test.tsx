import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clampSize, useBlobbyResize } from "./use-blobby-resize";

const deps = vi.hoisted(() => ({ resize: vi.fn(async () => {}), report: vi.fn() }));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  resizeBlobby: deps.resize,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: deps.report,
}));

function Probe({ size }: { size: number }) {
  const { ref, size: shown } = useBlobbyResize(size);
  return (
    <div ref={ref} data-testid="blobby">
      {shown.toFixed(2)}
    </div>
  );
}

function gesture(type: string, scale?: number) {
  const event = new Event(type, { cancelable: true });
  if (scale !== undefined) Object.assign(event, { scale });
  return event;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
});

afterEach(() => vi.useRealTimers());

describe("useBlobbyResize", () => {
  it("grows with a pinch at once and tells the shell after a moment", async () => {
    render(<Probe size={1} />);
    const node = screen.getByTestId("blobby");
    act(() => {
      node.dispatchEvent(gesture("gesturestart"));
      node.dispatchEvent(gesture("gesturechange", 1.3));
    });
    expect(node).toHaveTextContent("1.30");
    expect(deps.resize).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(100));
    expect(deps.resize).toHaveBeenCalledWith(1.3);
  });

  it("shrinks with the wheel under ⌘ or Ctrl, and ignores a plain scroll", async () => {
    const { rerender } = render(<Probe size={1} />);
    const node = screen.getByTestId("blobby");
    fireEvent.wheel(node, { deltaY: 10 });
    expect(node).toHaveTextContent("1.00");
    fireEvent.wheel(node, { deltaY: 30, metaKey: true });
    fireEvent.wheel(node, { deltaY: 30, ctrlKey: true });
    await act(async () => vi.advanceTimersByTimeAsync(100));
    expect(deps.resize).toHaveBeenCalledTimes(1);
    rerender(<Probe size={0.6} />);
    expect(node).toHaveTextContent("0.60");
  });

  it("keeps the hand's size while a later move is still on its way", async () => {
    let finish: () => void = () => {};
    deps.resize.mockReturnValueOnce(new Promise<void>((resolve) => (finish = resolve)));
    render(<Probe size={1} />);
    const node = screen.getByTestId("blobby");
    fireEvent.wheel(node, { deltaY: -20, ctrlKey: true });
    await act(async () => vi.advanceTimersByTimeAsync(100));
    fireEvent.wheel(node, { deltaY: -20, ctrlKey: true });
    await act(async () => finish());
    expect(node).not.toHaveTextContent("1.00");
  });

  it("reports a size the shell refused", async () => {
    deps.resize.mockRejectedValueOnce(new Error("refused"));
    render(<Probe size={1} />);
    fireEvent.wheel(screen.getByTestId("blobby"), { deltaY: 10, ctrlKey: true });
    await act(async () => vi.advanceTimersByTimeAsync(100));
    expect(deps.report).toHaveBeenCalledWith("could not resize blobby", expect.any(Error));
  });

  it("ignores a gesture event without a scale", () => {
    render(<Probe size={1} />);
    const node = screen.getByTestId("blobby");
    act(() => {
      node.dispatchEvent(gesture("gesturechange"));
    });
    expect(node).toHaveTextContent("1.00");
  });
});

describe("clampSize", () => {
  it("keeps a size in the shell's range", () => {
    expect(clampSize(0.1)).toBe(0.6);
    expect(clampSize(5)).toBe(1.6);
    expect(clampSize(1.2)).toBe(1.2);
  });
});
