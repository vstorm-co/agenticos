import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTurnElapsed, WorkFold, WorkingLine } from "./work-fold";

describe("useTurnElapsed", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-13T10:00:10Z"));
  });
  afterEach(() => vi.useRealTimers());

  const START = new Date("2026-10-13T10:00:00Z");

  it("ticks from the turn's own start while it runs, and freezes when it stops", () => {
    const { result, rerender } = renderHook(
      ({ running }: { running: boolean }) => useTurnElapsed(START, running),
      { initialProps: { running: true } },
    );
    act(() => vi.advanceTimersByTime(2000));
    expect(result.current).toBe(12_000);

    rerender({ running: false });
    act(() => vi.advanceTimersByTime(5000));
    expect(result.current).toBe(12_000);
  });

  it("keeps counting when the turn is rebuilt with an equal start, as every delta does", () => {
    // A streamed turn's message is rebuilt on every delta with an equal start.
    const { result, rerender } = renderHook(({ at }: { at: Date }) => useTurnElapsed(at, true), {
      initialProps: { at: new Date(START) },
    });
    for (let i = 0; i < 8; i += 1) {
      act(() => vi.advanceTimersByTime(250));
      rerender({ at: new Date(START) });
    }
    expect(result.current).toBe(12_000);
  });

  it("knows nothing of a turn it never watched", () => {
    const { result } = renderHook(() => useTurnElapsed(START, false));
    expect(result.current).toBeNull();
  });

  it("knows nothing without a start", () => {
    const { result } = renderHook(() => useTurnElapsed(undefined, true));
    act(() => vi.advanceTimersByTime(2000));
    expect(result.current).toBeNull();
  });
});

describe("WorkingLine", () => {
  it("says the turn is working before the first second has passed", () => {
    render(<WorkingLine elapsedMs={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Working…");
  });

  it("counts how long it has been working", () => {
    render(<WorkingLine elapsedMs={5_000} />);
    expect(screen.getByRole("status")).toHaveTextContent("Working for 5s…");
  });
});

describe("WorkFold", () => {
  it("names the work and its length, and opens onto it", () => {
    render(
      <WorkFold steps={3} durationMs={159_000}>
        <p>the steps</p>
      </WorkFold>,
    );
    const line = screen.getByRole("button", { name: "Worked for 2m 39s · 3 steps" });
    expect(screen.queryByText("the steps")).not.toBeInTheDocument();

    fireEvent.click(line);
    expect(line).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("the steps")).toBeInTheDocument();

    fireEvent.click(line);
    expect(screen.queryByText("the steps")).not.toBeInTheDocument();
  });

  it("counts the steps when the length is not known", () => {
    render(
      <WorkFold steps={1} durationMs={null}>
        {null}
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Worked · 1 step" })).toBeInTheDocument();
  });

  it("says a turn that only thought thought", () => {
    const { rerender } = render(
      <WorkFold steps={0} durationMs={8_000}>
        {null}
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Thought for 8s" })).toBeInTheDocument();

    rerender(
      <WorkFold steps={0} durationMs={null}>
        {null}
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Thought about it" })).toBeInTheDocument();
  });

  it("says a stopped run stopped, with or without its length", () => {
    const { rerender } = render(
      <WorkFold steps={2} durationMs={12_000} stopped>
        {null}
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Stopped after 12s · 2 steps" })).toBeInTheDocument();

    rerender(
      <WorkFold steps={0} durationMs={null} stopped>
        {null}
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Stopped" })).toBeInTheDocument();
  });
});
