import { forwardRef, type ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useTranslations } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DictationActions, DictationState } from "@/hooks/use-dictation";

import {
  dictationHint,
  DictationStrip,
  type DictationHintInput,
  type DictationUnavailable,
} from "./dictation-strip";

const motionState = vi.hoisted(() => ({ reduced: false }));

/**
 * `motion/react` with its timing made visible: each `motion.div` is a plain div
 * that writes the transition it was handed into an attribute, and presence is
 * immediate. What is under test is the transition the strip asks for, not the
 * library's animation of it.
 */
vi.mock("motion/react", () => {
  const MotionDiv = forwardRef<HTMLDivElement, Record<string, unknown>>(function MotionDiv(
    { transition, initial: _initial, animate: _animate, exit: _exit, children, ...rest },
    ref,
  ) {
    return (
      <div ref={ref} data-transition={JSON.stringify(transition)} {...rest}>
        {children as ReactNode}
      </div>
    );
  });
  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
    motion: { div: MotionDiv },
  };
});
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motionState.reduced }));

function dictationState(overrides: Partial<DictationState> = {}): DictationState {
  return {
    phase: "idle",
    elapsed: 42,
    remaining: null,
    silent: false,
    level: 0,
    reason: null,
    canRetry: false,
    retryAfter: null,
    transcript: null,
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
  };
}

/** The strip as the page draws it: the hint computed with the real catalog. */
function Harness(input: DictationHintInput) {
  const t = useTranslations("chat.dictation");
  return <DictationStrip hint={dictationHint(input, t)} />;
}

function show({
  state = {},
  unavailable = null,
  href = null,
  maxSeconds = 300,
}: {
  state?: Partial<DictationState>;
  unavailable?: DictationUnavailable | null;
  href?: string | null;
  maxSeconds?: number;
} = {}) {
  const actions = fakeActions();
  const closeExplanation = vi.fn();
  const view = render(
    <Harness
      state={dictationState(state)}
      actions={actions}
      maxSeconds={maxSeconds}
      unavailable={unavailable}
      voiceSettingsHref={href}
      closeExplanation={closeExplanation}
    />,
  );
  return { ...view, actions, closeExplanation };
}

/** The strip's box, which carries its background and its slide. */
const panel = () => screen.getByTestId("dictation-strip-panel");

beforeEach(() => {
  motionState.reduced = false;
});

describe("DictationStrip", () => {
  it("renders an empty polite region without a hint", () => {
    render(<DictationStrip hint={null} />);

    expect(screen.getByTestId("dictation-strip")).toBeEmptyDOMElement();
    expect(screen.getByTestId("dictation-strip")).toHaveAttribute("aria-live", "polite");
  });

  it("puts a hint into a live region that was already there, so it is read out", () => {
    const input = {
      actions: fakeActions(),
      maxSeconds: 300,
      unavailable: null,
      voiceSettingsHref: null,
      closeExplanation: vi.fn(),
    };
    const { rerender } = render(
      <Harness {...input} state={dictationState({ phase: "recording" })} />,
    );
    const region = screen.getByTestId("dictation-strip");
    expect(region).toBeEmptyDOMElement();

    rerender(<Harness {...input} state={dictationState({ phase: "recording", silent: true })} />);

    expect(screen.getByTestId("dictation-strip")).toBe(region);
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent("Can't hear you — is your microphone muted?");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("announces an error as an alert, with the polite region around it off", () => {
    const { unmount } = show({ state: { phase: "failed", reason: "too_large" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Recording too large to transcribe.");
    expect(screen.getByTestId("dictation-strip")).toHaveAttribute("aria-live", "off");
    expect(panel().className).toContain("bg-destructive/10");
    unmount();

    show({ state: { phase: "requesting" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("dictation-strip")).toHaveTextContent("Allow the microphone");
    expect(panel().className).toContain("bg-muted");
  });

  it("wraps its text and never cuts it", () => {
    show({ state: { phase: "failed", reason: "unsupported_type" } });

    let element: HTMLElement | null = screen.getByTestId("dictation-strip-text");
    while (element !== null) {
      expect(element.className).not.toMatch(/\b(truncate|line-clamp-\S+|whitespace-nowrap)\b/);
      element = element.parentElement;
    }
    expect(panel().className).toContain("break-words");
  });

  it("slides over 230 ms, and appears at once under reduced motion", () => {
    const { unmount } = show({ state: { phase: "requesting" } });
    expect(JSON.parse(panel().getAttribute("data-transition")!)).toMatchObject({
      duration: 0.23,
      ease: [0.22, 1, 0.36, 1],
    });
    unmount();

    motionState.reduced = true;
    show({ state: { phase: "requesting" } });
    for (const element of document.querySelectorAll("[data-transition]")) {
      expect(JSON.parse(element.getAttribute("data-transition")!)).toEqual({ duration: 0 });
    }
  });

  it("colours the warning's icon, not its background", () => {
    show({ state: { phase: "recording", remaining: 22 } });

    const strip = panel();
    expect(strip.className).toContain("bg-muted");
    expect(strip.querySelector("svg")!.getAttribute("class")).toContain("text-warning");
  });
});

describe("dictationHint", () => {
  it.each<[string, Parameters<typeof show>[0], RegExp, string[]]>([
    ["nothing while idle", { state: { phase: "idle" } }, /^$/, []],
    ["nothing while transcribing", { state: { phase: "transcribing" } }, /^$/, []],
    [
      "nothing while recording quietly within the limit",
      { state: { phase: "recording" } },
      /^$/,
      [],
    ],
    [
      "the permission prompt",
      { state: { phase: "requesting" } },
      /Allow the microphone in your browser's prompt to start recording\./,
      [],
    ],
    [
      "the countdown, with the limit it stops at",
      { state: { phase: "recording", remaining: 22 } },
      /0:22 left\. At 5:00 the recording stops and is transcribed\./,
      [],
    ],
    [
      "the countdown over the silence hint",
      { state: { phase: "recording", remaining: 9, silent: true }, maxSeconds: 60 },
      /0:09 left\. At 1:00/,
      [],
    ],
    [
      "the silence hint",
      { state: { phase: "recording", silent: true } },
      /Can't hear you — is your microphone muted\? Recording continues\./,
      [],
    ],
    [
      "a recording under a second",
      { state: { phase: "too_short" } },
      /That was under a second, so nothing was sent\./,
      ["Dismiss"],
    ],
    [
      "a blocked microphone, and how to unblock it",
      { state: { phase: "failed", reason: "mic_denied" } },
      /Microphone blocked for this site\. Click the icon left of the address bar/,
      ["Try again", "Dismiss"],
    ],
    [
      "a page that may not ask for the microphone",
      { state: { phase: "failed", reason: "mic_insecure" } },
      /This page can't use the microphone\. Browsers open the microphone only on HTTPS or on localhost/,
      ["Dismiss"],
    ],
    [
      "no microphone the browser can see",
      { state: { phase: "failed", reason: "mic_not_found" } },
      /No microphone found\. The browser sees no input device/,
      ["Try again", "Dismiss"],
    ],
    [
      "a microphone that would not start",
      { state: { phase: "failed", reason: "mic_busy" } },
      /The microphone didn't start\. Another app may be using it/,
      ["Try again", "Dismiss"],
    ],
    [
      "a recording with no speech in it",
      { state: { phase: "failed", reason: "empty" } },
      /No speech in that recording\./,
      ["Record again", "Dismiss"],
    ],
    [
      "a recording too large",
      { state: { phase: "failed", reason: "too_large" } },
      /Recording too large to transcribe\./,
      ["Dismiss"],
    ],
    [
      "an audio format the server refuses",
      { state: { phase: "failed", reason: "unsupported_type" } },
      /The server takes WebM, Ogg, MP4 or WAV audio\./,
      ["Dismiss"],
    ],
    [
      "a provider error, keeping the recording",
      { state: { phase: "failed", reason: "provider_error", canRetry: true } },
      /Transcription didn't finish\. The speech-to-text provider answered with an error\. Your 0:42 recording is kept until you retry or discard it\./,
      ["Retry", "Discard"],
    ],
    [
      "a provider that timed out",
      { state: { phase: "failed", reason: "timeout", canRetry: true } },
      /didn't answer in time\. Your 0:42 recording is kept/,
      ["Retry", "Discard"],
    ],
    [
      "a server out of reach",
      { state: { phase: "failed", reason: "offline", canRetry: true } },
      /The server couldn't be reached\./,
      ["Retry", "Discard"],
    ],
    [
      "the per-minute limit, with the wait on the button",
      { state: { phase: "failed", reason: "rate_limited", canRetry: true, retryAfter: 40 } },
      /Too many dictations in a minute\./,
      ["Retry in 40 s", "Discard"],
    ],
    [
      "a server not set up, to a member",
      { state: { phase: "failed", reason: "not_configured" } },
      /Dictation isn't set up yet\. .* Ask an admin to set it up\./,
      ["Dismiss"],
    ],
    [
      "the crossed-out mic, with no agent",
      { unavailable: "no_agent" },
      /Pick an agent first\./,
      ["Dismiss"],
    ],
    [
      "the crossed-out mic, not set up, to a member",
      { unavailable: "not_ready" },
      /Dictation isn't set up yet\. This organization transcribes on its own server, and no speech-to-text model is chosen\. Ask an admin to set it up\./,
      ["Dismiss"],
    ],
  ])("says %s", (_label, input, text, buttons) => {
    const { container } = show(input);

    expect(container.textContent).toMatch(text);
    const names = screen.queryAllByRole("button").map((button) => button.textContent);
    expect(names).toEqual(buttons);
  });

  it("links an org:settings holder to the Voice card instead of asking an admin", () => {
    show({ unavailable: "not_ready", href: "/orgs/o1/members#org-voice" });

    expect(screen.getByRole("link", { name: "Open Voice settings" })).toHaveAttribute(
      "href",
      "/orgs/o1/members#org-voice",
    );
    expect(screen.queryByText(/Ask an admin/)).not.toBeInTheDocument();
  });

  it("holds the rate-limited retry until the wait has passed", () => {
    show({ state: { phase: "failed", reason: "rate_limited", canRetry: true, retryAfter: 12 } });

    expect(screen.getByRole("button", { name: "Retry in 12 s" })).toBeDisabled();
  });

  it.each<[string, Partial<DictationState>, string, keyof DictationActions]>([
    ["Retry", { phase: "failed", reason: "provider_error", canRetry: true }, "Retry", "retry"],
    ["Discard", { phase: "failed", reason: "timeout", canRetry: true }, "Discard", "dismiss"],
    ["Try again", { phase: "failed", reason: "mic_denied" }, "Try again", "start"],
    ["Try again (no device)", { phase: "failed", reason: "mic_not_found" }, "Try again", "start"],
    ["Record again", { phase: "failed", reason: "empty" }, "Record again", "start"],
    ["Dismiss", { phase: "too_short" }, "Dismiss", "dismiss"],
  ])("%s calls the hook", async (_label, state, button, action) => {
    const { actions } = show({ state });

    await userEvent.click(within(document.body).getByRole("button", { name: button }));

    expect(actions[action]).toHaveBeenCalledOnce();
  });

  it.each<DictationUnavailable>(["no_agent", "not_ready"])(
    "closes the %s explanation on Dismiss",
    async (unavailable) => {
      const { actions, closeExplanation } = show({ unavailable });

      await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

      expect(closeExplanation).toHaveBeenCalledOnce();
      expect(actions.dismiss).not.toHaveBeenCalled();
    },
  );
});
