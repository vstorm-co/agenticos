import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

it("lets the live progress line expand and collapse with the keyboard", async () => {
  const toggle = vi.fn();
  render(<WorkingLine elapsedMs={5000} expanded={false} onToggle={toggle} />);
  const button = screen.getByRole("button", { name: "Working for 5s…" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  button.focus();
  await userEvent.keyboard("{Enter}");
  expect(toggle).toHaveBeenCalledOnce();
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

describe("waiting activity", () => {
  it("shows a waiting state instead of a ticking working status", () => {
    render(
      <WorkFold steps={4} durationMs={600_000} waiting="awaiting_answer">
        <span>tools</span>
      </WorkFold>,
    );
    expect(screen.getByRole("button", { name: "Waiting for an answer" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText(/Working/)).toBeNull();
  });
});

it("updates one compact live disclosure without exposing its detailed steps", async () => {
  const { rerender } = render(
    <WorkFold steps={7} durationMs={18_000} running activity="List inbox cases">
      <p>Detailed tool arguments</p>
    </WorkFold>,
  );
  const toggle = screen.getByRole("button", { name: /Working for 18s/ });
  expect(toggle).toHaveTextContent("List inbox cases");
  expect(screen.queryByText("Detailed tool arguments")).toBeNull();
  rerender(
    <WorkFold steps={7} durationMs={19_000} running activity="Thinking...">
      <p>Detailed tool arguments</p>
    </WorkFold>,
  );
  expect(screen.getByRole("button", { name: /Working for 19s/ })).toBe(toggle);
  expect(toggle).toHaveTextContent("Thinking...");
  expect(screen.queryByText("List inbox cases")).toBeNull();
  await userEvent.click(toggle);
  expect(screen.getByText("Detailed tool arguments")).toBeVisible();
  expect(screen.queryByText("Thinking...")).toBeNull();
});

it("opens the full history as a labelled keyboard-accessible scroll region", async () => {
  render(
    <WorkFold steps={40} durationMs={120_000}>
      {Array.from({ length: 40 }, (_, index) => (
        <p key={index}>Step {index + 1}</p>
      ))}
    </WorkFold>,
  );
  const toggle = screen.getByRole("button", { name: /Worked for 2m/ });
  expect(screen.queryByRole("region")).toBeNull();
  await userEvent.click(toggle);
  const history = screen.getByRole("region", { name: /Worked for 2m/ });
  expect(toggle).toHaveAttribute("aria-controls", history.id);
  expect(screen.getByText("Step 40")).toBeInTheDocument();
  await userEvent.tab();
  expect(history).toHaveFocus();
  await userEvent.click(toggle);
  expect(screen.queryByRole("region")).toBeNull();
});

it("does not label failed work as completed", () => {
  render(
    <WorkFold steps={2} durationMs={10_000} failed>
      <p>the steps</p>
    </WorkFold>,
  );
  expect(screen.getByRole("button", { name: "Failed after 10s · 2 steps" })).toBeInTheDocument();
  expect(screen.queryByText(/Worked/)).not.toBeInTheDocument();
});

it("marks failed work even when the duration was not recorded", () => {
  render(
    <WorkFold steps={2} durationMs={null} failed>
      <p>the steps</p>
    </WorkFold>,
  );
  expect(screen.getByRole("button", { name: "Failed · 2 steps" })).toBeInTheDocument();
});
