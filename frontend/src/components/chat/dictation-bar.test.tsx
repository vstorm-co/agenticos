import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DictationActions, DictationState, LevelMeter } from "@/hooks/use-dictation";

import { clock, DictationBar } from "./dictation-bar";

const motionState = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motionState.reduced }));

/** A meter that reads `level` - and, written, tells whoever subscribed. */
function at(level: number): LevelMeter & { write: (next: number) => void } {
  let now = level;
  const listeners = new Set<() => void>();
  return {
    read: () => now,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    write: (next) => {
      now = next;
      listeners.forEach((listener) => listener());
    },
  };
}

function dictationState(overrides: Partial<DictationState> = {}): DictationState {
  return {
    phase: "recording",
    elapsed: 7,
    remaining: null,
    silent: false,
    meter: { read: () => 0, subscribe: () => () => {} },
    reason: null,
    canRetry: false,
    retryAfter: null,
    transcript: null,
    upload: null,
    stoppedAtLimit: false,
    inserted: false,
    ...overrides,
  };
}

function fakeActions(): DictationActions {
  return {
    start: vi.fn(async () => {}),
    stop: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
    dismiss: vi.fn(),
    dismissInserted: vi.fn(),
  };
}

beforeEach(() => {
  motionState.reduced = false;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("clock", () => {
  it.each([
    [0, "0:00"],
    [7, "0:07"],
    [65, "1:05"],
    [600, "10:00"],
    [-3, "0:00"],
  ])("shows %i seconds as %s", (seconds, shown) => {
    expect(clock(seconds)).toBe(shown);
  });
});

describe("DictationBar", () => {
  it("counts the upload while it is going up, and pulses only once it is up", () => {
    const { rerender } = render(
      <DictationBar
        state={dictationState({ phase: "transcribing", upload: 42 })}
        actions={fakeActions()}
      />,
    );

    expect(screen.getByTestId("dictation-upload")).toHaveTextContent("Uploading 42%");
    expect(screen.queryByText("Transcribing")).toBeNull();
    expect(screen.getByText("0:07 of audio")).toBeInTheDocument();

    rerender(
      <DictationBar state={dictationState({ phase: "transcribing" })} actions={fakeActions()} />,
    );

    expect(screen.queryByTestId("dictation-upload")).toBeNull();
    expect(screen.getByText("Transcribing")).toHaveClass("motion-safe:animate-pulse");
  });

  it("holds Cancel, the clock and Stop while recording, and nothing else", async () => {
    const actions = fakeActions();
    render(<DictationBar state={dictationState()} actions={actions} />);

    const cancel = screen.getByRole("button", { name: "Cancel dictation" });
    const stop = screen.getByRole("button", { name: "Stop and transcribe" });
    expect(cancel).toHaveAttribute("title", "Cancel (Esc)");
    expect(stop).toHaveAttribute("title", "Stop and transcribe (Enter)");
    expect(screen.getByRole("timer", { name: "Recording time" })).toHaveTextContent("0:07");
    expect(screen.getAllByRole("button")).toHaveLength(2);

    await userEvent.click(stop);
    await userEvent.click(cancel);
    expect(actions.stop).toHaveBeenCalledOnce();
    expect(actions.cancel).toHaveBeenCalledOnce();
  });

  it("has nothing to stop while the browser is still asking", () => {
    render(
      <DictationBar
        state={dictationState({ phase: "requesting", elapsed: 0 })}
        actions={fakeActions()}
      />,
    );

    expect(screen.getByRole("button", { name: "Stop and transcribe" })).toBeDisabled();
    expect(screen.getByRole("timer")).toHaveTextContent("0:00");
    expect(screen.getByRole("timer").className).toContain("text-muted-foreground");
  });

  it("moves focus to Stop the moment the recording is live", () => {
    const actions = fakeActions();
    const { rerender } = render(
      <DictationBar state={dictationState({ phase: "requesting" })} actions={actions} />,
    );

    rerender(<DictationBar state={dictationState()} actions={actions} />);

    expect(screen.getByRole("button", { name: "Stop and transcribe" })).toHaveFocus();
  });

  it("hands focus to Cancel when Stop goes away, so Escape still reaches the form", () => {
    const actions = fakeActions();
    const { rerender } = render(<DictationBar state={dictationState()} actions={actions} />);
    expect(screen.getByRole("button", { name: "Stop and transcribe" })).toHaveFocus();

    rerender(<DictationBar state={dictationState({ phase: "transcribing" })} actions={actions} />);

    expect(screen.getByRole("button", { name: "Cancel transcription" })).toHaveFocus();
  });

  it("leaves focus alone when it is somewhere else as transcribing starts", () => {
    const actions = fakeActions();
    const { rerender } = render(
      <>
        <textarea aria-label="Message" />
        <DictationBar state={dictationState()} actions={actions} />
      </>,
    );
    screen.getByRole("textbox", { name: "Message" }).focus();

    rerender(
      <>
        <textarea aria-label="Message" />
        <DictationBar state={dictationState({ phase: "transcribing" })} actions={actions} />
      </>,
    );

    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
  });

  it("says it is transcribing, and how much audio, with Cancel still there", async () => {
    const actions = fakeActions();
    render(
      <DictationBar
        state={dictationState({ phase: "transcribing", elapsed: 42 })}
        actions={actions}
      />,
    );

    expect(screen.getByText("Transcribing", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("0:42 of audio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcribing" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Cancel transcription" }));
    expect(actions.cancel).toHaveBeenCalledOnce();
  });

  it("draws the level as a scrolling waveform", async () => {
    vi.useFakeTimers();
    const actions = fakeActions();
    const { rerender } = render(
      <DictationBar state={dictationState({ meter: at(0.5) })} actions={actions} />,
    );
    const bars = () => [...screen.getByTestId("waveform").children] as HTMLElement[];
    expect(bars()).toHaveLength(64);
    expect(bars().at(-1)!.style.transform).toBe("scaleY(0.12)");

    act(() => vi.advanceTimersByTime(70));
    expect(bars().at(-1)!.style.transform).toBe("scaleY(0.5)");

    rerender(<DictationBar state={dictationState({ meter: at(1.4) })} actions={actions} />);
    act(() => vi.advanceTimersByTime(70));
    expect(bars().at(-1)!.style.transform).toBe("scaleY(1)");
    expect(bars().at(-2)!.style.transform).toBe("scaleY(0.5)");
    expect(screen.queryByTestId("level-steps")).not.toBeInTheDocument();
  });

  it("follows the meter on its own, with no new state from the page", () => {
    vi.useFakeTimers();
    const meter = at(0);
    render(<DictationBar state={dictationState({ meter })} actions={fakeActions()} />);
    const bars = () => [...screen.getByTestId("waveform").children] as HTMLElement[];

    act(() => meter.write(0.5));
    act(() => vi.advanceTimersByTime(70));

    expect(bars().at(-1)!.style.transform).toBe("scaleY(0.5)");
  });

  it("keeps the waveform flat while the browser is still asking", () => {
    vi.useFakeTimers();
    render(
      <DictationBar
        state={dictationState({ phase: "requesting", meter: at(0.8) })}
        actions={fakeActions()}
      />,
    );

    act(() => vi.advanceTimersByTime(700));

    const bars = [...screen.getByTestId("waveform").children] as HTMLElement[];
    expect(bars.every((bar) => bar.style.transform === "scaleY(0.12)")).toBe(true);
  });

  it.each([
    [0, 0],
    [0.31, 2],
    [0.62, 3],
    [1, 5],
  ])("under reduced motion lights the steps for level %s: %i of 5", (level, on) => {
    motionState.reduced = true;
    render(<DictationBar state={dictationState({ meter: at(level) })} actions={fakeActions()} />);

    const steps = [...screen.getByTestId("level-steps").children];
    expect(steps).toHaveLength(5);
    expect(steps.filter((step) => step.getAttribute("data-on") === "true")).toHaveLength(on);
    expect(screen.queryByTestId("waveform")).not.toBeInTheDocument();
  });

  it("gives Cancel and Stop a 44 px target on a coarse pointer", () => {
    render(<DictationBar state={dictationState()} actions={fakeActions()} />);

    for (const name of ["Cancel dictation", "Stop and transcribe"]) {
      const button = screen.getByRole("button", { name });
      expect(button.className).toContain("pointer-coarse:h-11");
      expect(button.className).toContain("pointer-coarse:w-11");
    }
  });
});
