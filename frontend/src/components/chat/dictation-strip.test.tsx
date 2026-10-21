import { forwardRef, type ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createTranslator, useTranslations } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DictationActions, DictationState } from "@/hooks/use-dictation";

import de from "../../../messages/de.json";
import en from "../../../messages/en.json";
import pl from "../../../messages/pl.json";

import { dictationHint, DictationStrip, movesOn, type DictationHintInput } from "./dictation-strip";

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

/** The strip as the page draws it: the hint computed with the real catalog. */
function Harness(input: DictationHintInput) {
  const t = useTranslations("chat.dictation");
  return <DictationStrip hint={dictationHint(input, t)} />;
}

function show({
  state = {},
  href = null,
  agentHref = null,
  maxSeconds = 300,
}: {
  state?: Partial<DictationState>;
  href?: string | null;
  agentHref?: string | null;
  maxSeconds?: number;
} = {}) {
  const actions = fakeActions();
  const view = render(
    <Harness
      state={dictationState(state)}
      actions={actions}
      maxSeconds={maxSeconds}
      voiceSettingsHref={href}
      agentVoiceHref={agentHref}
    />,
  );
  return { ...view, actions };
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
      voiceSettingsHref: null,
      agentVoiceHref: null,
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
      "the auto-stop at the limit, while that recording is transcribed",
      { state: { phase: "transcribing", stoppedAtLimit: true }, maxSeconds: 10 },
      /^Stopped at the 0:10 limit\. Transcribing everything up to here\.$/,
      [],
    ],
    [
      "the words a transcript inserted",
      { state: { inserted: true, transcript: { id: 3, text: "focus on churn, three bullets" } } },
      /^Inserted 5 words$/,
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
      /isn.t in a format the server accepts\./,
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
      "a session that ended, keeping nothing",
      { state: { phase: "failed", reason: "signed_out" } },
      /^You're signed out\. Sign in again, then record again\./,
      ["Dismiss"],
    ],
    [
      "a person who may not dictate to this agent, keeping nothing",
      { state: { phase: "failed", reason: "forbidden" } },
      /^You're not allowed to dictate to this agent\. Ask an admin for access to it\./,
      ["Dismiss"],
    ],
    [
      "a server not set up, to a member",
      { state: { phase: "failed", reason: "not_configured" } },
      /Dictation isn't set up\. This agent's speech-to-text provider has no usable key any more\. Ask an admin to set it up\./,
      ["Dismiss"],
    ],
  ])("says %s", (_label, input, text, buttons) => {
    const { container } = show(input);

    expect(container.textContent).toMatch(text);
    const names = screen.queryAllByRole("button").map((button) => button.textContent);
    expect(names).toEqual(buttons);
  });

  it("says nothing of the words that landed where the composer announces them itself", () => {
    const input = {
      actions: fakeActions(),
      maxSeconds: 300,
      voiceSettingsHref: null,
      agentVoiceHref: null,
    };
    const state = dictationState({ inserted: true, transcript: { id: 1, text: "hello" } });
    const { rerender } = render(<Harness {...input} state={state} />);
    // The default: a page with no announcement of its own says it from here.
    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent("Inserted 1 word");
    expect(screen.getByTestId("dictation-strip")).toHaveAttribute("aria-live", "polite");

    rerender(<Harness {...input} state={state} insertAnnounced />);

    expect(screen.queryByTestId("dictation-strip-text")).not.toBeInTheDocument();
  });

  it.each<[string, Record<string, unknown>, string, [number, string][]]>([
    [
      "en",
      en,
      "chat.dictation",
      [
        [1, "Inserted 1 word"],
        [2, "Inserted 2 words"],
        [5, "Inserted 5 words"],
      ],
    ],
    [
      "pl",
      pl,
      "chat.dictation",
      [
        [1, "Wstawiono 1 słowo"],
        [3, "Wstawiono 3 słowa"],
        [5, "Wstawiono 5 słów"],
        [22, "Wstawiono 22 słowa"],
        [25, "Wstawiono 25 słów"],
      ],
    ],
    [
      "pl",
      pl,
      "hosted.dictation",
      [
        [1, "Wstawiono 1 słowo"],
        [4, "Wstawiono 4 słowa"],
        [12, "Wstawiono 12 słów"],
      ],
    ],
    [
      "de",
      de,
      "chat.dictation",
      [
        [1, "1 Wort eingefügt"],
        [7, "7 Wörter eingefügt"],
      ],
    ],
  ])("counts inserted words in %s (%s)", (locale, messages, namespace, cases) => {
    const t = createTranslator({
      locale,
      messages,
      namespace,
    } as never) as unknown as Parameters<typeof dictationHint>[1];
    for (const [count, expected] of cases) {
      const text = Array.from({ length: count }, (_, i) => `w${i}`).join(" ");
      const { unmount } = render(
        <DictationStrip
          hint={dictationHint(
            {
              state: dictationState({ inserted: true, transcript: { id: count, text } }),
              actions: fakeActions(),
              maxSeconds: 300,
              voiceSettingsHref: null,
              agentVoiceHref: null,
            },
            t,
          )}
        />,
      );
      expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent(expected);
      unmount();
    }
  });

  it("states the limit the same way in every catalog", () => {
    for (const messages of [en, pl, de]) {
      const t = createTranslator({
        locale: "en",
        messages,
        namespace: "hosted.dictation",
      } as never) as unknown as Parameters<typeof dictationHint>[1];
      const { unmount } = render(
        <DictationStrip
          hint={dictationHint(
            {
              state: dictationState({ phase: "transcribing", stoppedAtLimit: true }),
              actions: fakeActions(),
              maxSeconds: 300,
              voiceSettingsHref: null,
              agentVoiceHref: null,
              visitor: true,
            },
            t,
          )}
        />,
      );
      expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent("5:00");
      unmount();
    }
  });

  it("tells a hosted page's visitor what to do instead, naming no admin and no setting", () => {
    // A visitor has nobody to ask and nowhere to go: the copy is the visitor's own
    // namespace, and the sentence about the admin is not built at all.
    function Visitor(input: DictationHintInput) {
      const t = useTranslations("hosted.dictation");
      return <DictationStrip hint={dictationHint(input, t)} />;
    }
    const { container } = render(
      <Visitor
        state={dictationState({ phase: "failed", reason: "not_configured" })}
        actions={fakeActions()}
        maxSeconds={300}
        voiceSettingsHref={null}
        agentVoiceHref={null}
        visitor
      />,
    );

    expect(container.textContent).toMatch(
      /^Voice input isn't available right now\. Please type your message instead\.Dismiss$/,
    );
  });

  it("links an org:settings holder to the Voice card instead of asking an admin", () => {
    show({
      state: { phase: "failed", reason: "not_configured" },
      href: "/orgs/o1/members#org-voice",
    });

    expect(screen.getByRole("link", { name: "Open Voice settings" })).toHaveAttribute(
      "href",
      "/orgs/o1/members#org-voice",
    );
    expect(screen.queryByText(/Ask an admin/)).not.toBeInTheDocument();
  });

  it("offers both the organization's settings and this agent's, side by side", () => {
    show({
      state: { phase: "failed", reason: "not_configured" },
      href: "/orgs/o1/members#org-voice",
      agentHref: "/agents/a1#agent-voice",
    });

    expect(screen.getByRole("link", { name: "Set one for this agent" })).toHaveAttribute(
      "href",
      "/agents/a1#agent-voice",
    );
    expect(screen.getByRole("link", { name: "Open Voice settings" })).toBeInTheDocument();
    expect(panel().textContent).toContain("Open Voice settings · Set one for this agent");
  });

  it("links an agent editor without org settings to the agent alone", () => {
    show({
      state: { phase: "failed", reason: "not_configured" },
      agentHref: "/agents/a1#agent-voice",
    });

    expect(screen.getByRole("link", { name: "Set one for this agent" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Voice settings" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Ask an admin/)).not.toBeInTheDocument();
  });

  it("holds the rate-limited retry until the wait has passed, under a name that does not tick", () => {
    const { rerender, actions } = show({
      state: { phase: "failed", reason: "rate_limited", canRetry: true, retryAfter: 12 },
    });
    const retry = screen.getByRole("button", { name: "Retry" });
    expect(retry).toBeDisabled();
    expect(retry).toHaveTextContent("Retry in 12 s");

    const later = (
      <Harness
        state={dictationState({
          phase: "failed",
          reason: "rate_limited",
          canRetry: true,
          retryAfter: 11,
        })}
        actions={actions}
        maxSeconds={300}
        voiceSettingsHref={null}
        agentVoiceHref={null}
      />
    );
    rerender(later);

    // Inside the alert only the accessible name is read, and it held still.
    expect(screen.getByRole("button", { name: "Retry" })).toHaveTextContent("Retry in 11 s");
    expect(screen.getByText("Retry in 11 s")).toHaveAttribute("aria-hidden", "true");
  });

  it("reads the countdown out once: the ticking clock is hidden, the spoken sentence holds still", () => {
    const at = (remaining: number) => (
      <Harness
        state={dictationState({ phase: "recording", remaining })}
        actions={fakeActions()}
        maxSeconds={300}
        voiceSettingsHref={null}
        agentVoiceHref={null}
      />
    );
    const { rerender } = render(at(22));
    const spoken = () => screen.getByText(/The recording is about to stop\./).closest("span")!;
    const before = spoken().textContent;

    rerender(at(21));

    expect(screen.getByText("0:21 left.").closest("[aria-hidden]")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(spoken()).toHaveClass("sr-only");
    expect(spoken().textContent).toBe(before);
    expect(before).toBe("The recording is about to stop. At 5:00 it stops and is transcribed.");
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
});

describe("movesOn", () => {
  it.each([
    ["a", true],
    ["Enter", true],
    ["ArrowLeft", true],
    ["Backspace", true],
    ["Shift", false],
    ["Control", false],
    ["Alt", false],
    ["Meta", false],
  ])("reads %s as moving on: %s", (key, expected) => {
    expect(movesOn(key)).toBe(expected);
  });
});
