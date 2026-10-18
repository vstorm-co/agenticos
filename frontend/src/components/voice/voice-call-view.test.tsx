import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DictationStrip } from "@/components/chat/dictation-strip";
import type { VoiceSession } from "@/hooks/use-voice-session";
import {
  callReducer,
  initialCall,
  viewState,
  type CallAction,
  type CallState,
} from "@/lib/voice/call-reducer";
import { useMotionStore, useVoiceCallStore, useVoiceGlowStore } from "@/stores";
import type { VoiceServerFrame } from "@/types/voice";

import { voiceFailureHint } from "./voice-call-strip";
import { callActive, showVoiceApproval, VoiceCallBar, VoiceCallFeed } from "./voice-call-view";

const NOW = 1_000_000;

const READY: VoiceServerFrame = {
  type: "ready",
  call_id: "c1",
  run_id: "r1",
  conversation_id: "conv1",
  transport: "webrtc",
  input_sample_rate: 24000,
  output_sample_rate: 24000,
  cap_seconds: 600,
  minutes_left: 540,
  resume_token: "tok1",
};

const APPROVAL: VoiceServerFrame = {
  type: "approval_required",
  id: "a1",
  tool: "send_invoice",
  args: { customer: "Ahmad", amount_eur: 120 },
  said: "Send an invoice for 120 euros to Acme",
  timeout_seconds: 60,
};

const frame = (f: VoiceServerFrame, now = NOW): CallAction => ({ type: "frame", frame: f, now });

/** A call driven through the reducer, as the hook drives it. */
function drive(...actions: CallAction[]): CallState {
  return actions.reduce(callReducer, initialCall);
}

const connecting = (): CallState => drive({ type: "connecting" });
const live = (...more: CallAction[]): CallState =>
  drive({ type: "connecting" }, frame(READY), ...more);
const state = (s: VoiceServerFrame & { type: "state" }) => frame(s);

/** Every designed state, built the way the call reaches it. */
const STATES: Record<string, () => CallState> = {
  connecting,
  listening: () => live(),
  user: () => live(state({ type: "state", state: "user_speaking" })),
  thinking: () => live(state({ type: "state", state: "thinking" })),
  agent: () => live(state({ type: "state", state: "agent_speaking" })),
  interrupted: () => live(state({ type: "state", state: "interrupted" })),
  tool: () =>
    live(
      frame({ type: "tool", name: "web_search", status: "running" }),
      state({ type: "state", state: "tool_running" }),
    ),
  approval: () => live(frame(APPROVAL)),
  noapproval: () =>
    live(frame({ type: "approval_unavailable", tool: "send_invoice", args: { customer: "Acme" } })),
  limitwarn: () => live(frame({ type: "limit", seconds_left: 60 })),
  limitend: () => live(frame({ type: "ended", reason: "time_limit" }, NOW + 600_000)),
  ended: () => live(frame({ type: "ended", reason: "user" }, NOW + 222_000)),
  micblocked: () => drive({ type: "connecting" }, { type: "mic_failed", failure: "mic_denied" }),
  connfailed: () => drive({ type: "connecting" }, { type: "socket_lost", willRetry: false }),
  reconnecting: () => live({ type: "socket_lost", willRetry: true }),
  dropped: () => live({ type: "socket_lost", willRetry: false }),
};

/** What each state says, wherever the layout puts it. */
const SAYS: Record<string, RegExp> = {
  connecting: /Allow the microphone/,
  listening: /^Listening$/,
  user: /^You're speaking$/,
  thinking: /^Thinking/,
  agent: /^Support is speaking$/,
  interrupted: /^Interrupted$/,
  tool: /^Searching the web$/,
  approval: /^Waiting for your approval$/,
  noapproval: /needs an approval you can't give here/,
  limitwarn: /left in this call/,
  limitend: /^Call ended at the 10-minute limit$/,
  ended: /^Voice call ended · 3:42$/,
  micblocked: /Microphone blocked for this site/,
  connfailed: /The call couldn't connect/,
  reconnecting: /^Reconnecting…$/,
  dropped: /^Call dropped$/,
};

function fake(call: CallState, overrides: Partial<VoiceSession> = {}): VoiceSession {
  return {
    call,
    localStream: null,
    remoteStream: null,
    start: vi.fn(),
    end: vi.fn(),
    setMuted: vi.fn(),
    pressToTalk: vi.fn(),
    decide: vi.fn(),
    answer: vi.fn(),
    dismissUnavailable: vi.fn(),
    dismiss: vi.fn(),
    ...overrides,
  };
}

/** The view as `/chat` composes it: the feed in the conversation, the bar or the composer's strip below. */
function View({
  session,
  onCallAgain = () => {},
  onShowApproval = () => {},
  canDecide = true,
}: {
  session: VoiceSession;
  onCallAgain?: () => void;
  onShowApproval?: () => void;
  canDecide?: boolean;
}) {
  const t = useTranslations("chat.voice");
  return (
    <>
      <VoiceCallFeed
        session={session}
        agentName="Support"
        canDecide={canDecide}
        hidden={new Set()}
        onCallAgain={onCallAgain}
        onContinueInText={session.end}
      />
      {callActive(session) ? (
        <VoiceCallBar
          session={session}
          agentName="Support"
          canDecide={canDecide}
          onShowApproval={onShowApproval}
        />
      ) : (
        <DictationStrip
          hint={voiceFailureHint(
            { call: session.call, onRetry: onCallAgain, onDismiss: session.dismiss },
            t,
          )}
        />
      )}
    </>
  );
}

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(NOW + 12_000);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  useVoiceCallStore.setState({ pushToTalk: false });
  useVoiceGlowStore.setState({ style: "vivid" });
  useMotionStore.setState({ motion: "full" });
});

afterEach(() => vi.restoreAllMocks());

describe("the call view", () => {
  it.each(Object.keys(STATES))("has a look and words of its own for %s", (name) => {
    const call = (STATES[name] as () => CallState)();
    expect(viewState(call)).toBe(name);
    render(<View session={fake(call)} />);
    expect(screen.getAllByText(SAYS[name] as RegExp).length).toBeGreaterThan(0);
  });

  it("stands the bar in for the composer only while a call is on", () => {
    expect(callActive(fake(initialCall))).toBe(false);
    expect(callActive(fake(connecting()))).toBe(true);
    expect(callActive(fake((STATES.reconnecting as () => CallState)()))).toBe(true);
    expect(callActive(fake((STATES.ended as () => CallState)()))).toBe(false);
    const { container } = render(<View session={fake(initialCall)} />);
    expect(container.querySelector('[data-testid="voice-call-feed"]')).toBeNull();
  });

  it("shows the approval with its exact arguments, decides by button, and points back to it", () => {
    const decide = vi.fn();
    const onShowApproval = vi.fn();
    render(
      <View session={fake(live(frame(APPROVAL)), { decide })} onShowApproval={onShowApproval} />,
    );
    const card = screen.getByRole("group", { name: "Approve Send Invoice?" });
    expect(within(card).getByText("Ahmad")).toBeInTheDocument();
    expect(within(card).getByText(/Send an invoice for 120 euros to Acme/)).toBeInTheDocument();
    // The countdown runs from the frame's own timeout: 12 s in, 48 left.
    expect(within(card).getByText("Auto-deny in 0:48")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Deny" }));
    expect(decide).toHaveBeenCalledWith("a1", false);
    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent(
      "Approve or deny the request above. Denied automatically in 0:48.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Show card" }));
    expect(onShowApproval).toHaveBeenCalledOnce();
  });

  it("points at no buttons for a caller who cannot decide", () => {
    render(<View session={fake(live(frame(APPROVAL)))} canDecide={false} />);
    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent(
      "Approve or deny the request above",
    );
    expect(screen.queryByRole("button", { name: "Show card" })).toBeNull();
  });

  it("unmutes when push to talk is turned on, so a held microphone is open", () => {
    const setMuted = vi.fn();
    render(<View session={fake(live({ type: "muted", muted: true }), { setMuted })} />);
    fireEvent.click(screen.getByRole("button", { name: "Push to talk" }));
    expect(setMuted).toHaveBeenCalledWith(false);
    expect(useVoiceCallStore.getState().pushToTalk).toBe(true);
  });

  it("announces how the call ended in a region that was there before it ended", () => {
    const { rerender } = render(<View session={fake(live())} />);
    const region = screen.getByTestId("voice-call-end");
    expect(region).toHaveAttribute("role", "status");
    expect(region).toBeEmptyDOMElement();
    rerender(<View session={fake(live(frame({ type: "ended", reason: "user" }, NOW + 5000)))} />);
    expect(screen.getByTestId("voice-call-end")).toBe(region);
    expect(region).toHaveTextContent("Voice call ended · 0:05");
  });

  it("says a call refused for a reason with no words of its own simply ended", () => {
    render(
      <View
        session={fake(drive({ type: "connecting" }, frame({ type: "ended", reason: "error" })))}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The call didn't start. The call ended");
  });

  it("asks the agent's questions on the chat's card and sends what was picked", () => {
    const answer = vi.fn();
    const questions = frame({
      type: "questions",
      id: "q1",
      questions: [
        {
          question: "Which size?",
          header: "Size",
          options: [{ label: "Small" }, { label: "Large" }],
          allow_custom: true,
        },
      ],
      timeout_seconds: 120,
    });
    render(<View session={fake(live(questions), { answer })} />);
    fireEvent.click(screen.getByRole("button", { name: /Large/ }));
    expect(answer).toHaveBeenCalledWith("q1", [
      expect.objectContaining({ selected: ["Large"], skipped: false }),
    ]);
  });

  it("keeps a decided approval in the conversation as its record", () => {
    render(
      <View
        session={fake(
          live(frame(APPROVAL), frame({ type: "approval_settled", id: "a1", outcome: "expired" })),
        )}
      />,
    );
    expect(
      screen.getByRole("group", { name: "Denied automatically: no decision within 60 seconds" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Approve Send Invoice?" })).toBeNull();
  });

  it("lets a caller who cannot approve keep talking or end the call for text", () => {
    const end = vi.fn();
    const dismissUnavailable = vi.fn();
    render(
      <View
        session={fake((STATES.noapproval as () => CallState)(), { end, dismissUnavailable })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep talking" }));
    fireEvent.click(screen.getByRole("button", { name: "End call, continue in text" }));
    expect(dismissUnavailable).toHaveBeenCalledOnce();
    expect(end).toHaveBeenCalledOnce();
  });

  it("draws the caption inside the message being spoken, and the running tool where the answer goes", () => {
    render(
      <View
        session={fake(
          live(
            frame({
              type: "caption",
              role: "user",
              turn_id: "c1:1:user",
              part: 0,
              final: "Weather?",
            }),
            frame({ type: "tool", name: "web_search", status: "running" }),
            state({ type: "state", state: "tool_running" }),
          ),
        )}
      />,
    );
    expect(screen.getByTestId("voice-captions-visible")).toHaveTextContent("Weather?");
    expect(screen.getAllByText("web_search").length).toBeGreaterThan(0);
  });

  it("ends only by End, and moves focus into the bar when the call starts", () => {
    const end = vi.fn();
    render(<View session={fake(live(), { end })} />);
    const bar = screen.getByRole("group", { name: "Voice call" });
    expect(bar).toHaveFocus();
    fireEvent.keyDown(bar, { key: "Escape" });
    expect(end).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "End call" }));
    expect(end).toHaveBeenCalledOnce();
  });

  it("ticks the call's clock once a second", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    const now = vi.mocked(Date.now);
    render(<View session={fake(live())} />);
    expect(screen.getByText("0:12")).toBeInTheDocument();
    now.mockReturnValue(NOW + 13_000);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("0:13")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("plays the agent's voice through an audio element with no controls", () => {
    const remote = { id: "agent", getAudioTracks: () => [] } as unknown as MediaStream;
    render(<View session={fake(live(), { remoteStream: remote })} />);
    const audio = screen.getByTestId("voice-call-audio") as HTMLAudioElement;
    expect(audio.srcObject).toBe(remote);
    expect(audio).not.toHaveAttribute("controls");
  });

  it("draws a canvas and the glow, coloured for the agent while it speaks", () => {
    const { container } = render(
      <View session={fake(live(state({ type: "state", state: "agent_speaking" })))} />,
    );
    expect(container.querySelector("canvas")).not.toBeNull();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByTestId("voice-call-glow")).toHaveAttribute("data-side", "agent");
  });

  it("keeps the glow in the person's ink, sweeping while the agent works, quiet for an approval", () => {
    useVoiceGlowStore.setState({ style: "subtle" });
    const { rerender } = render(
      <View session={fake(live(state({ type: "state", state: "agent_speaking" })))} />,
    );
    expect(screen.getByTestId("voice-call-glow")).toHaveAttribute("data-side", "caller");
    rerender(<View session={fake(live(state({ type: "state", state: "thinking" })))} />);
    expect(screen.getByTestId("voice-call-glow")).toHaveAttribute("data-working", "thinking");
    rerender(<View session={fake(live(frame(APPROVAL)))} />);
    expect(screen.getByTestId("voice-call-glow")).toHaveAttribute("data-quiet");
  });

  it("draws no glow for a person who turned it off", () => {
    useVoiceGlowStore.setState({ style: "off" });
    render(<View session={fake(live())} />);
    expect(screen.queryByTestId("voice-call-glow")).toBeNull();
  });

  it("swaps the canvas and glow for a stepped meter under reduced motion", () => {
    useMotionStore.setState({ motion: "reduce" });
    const { container, rerender } = render(<View session={fake(live())} />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(screen.queryByTestId("voice-call-glow")).toBeNull();
    expect(screen.getByRole("meter", { name: "You" })).toBeInTheDocument();
    rerender(<View session={fake(live(state({ type: "state", state: "agent_speaking" })))} />);
    expect(screen.getByRole("meter", { name: "Support" })).toBeInTheDocument();
    rerender(<View session={fake(live({ type: "muted", muted: true }))} />);
    expect(screen.getByRole("meter", { name: "Mic off" })).toBeInTheDocument();
  });

  it("explains push to talk under the bar, and holds the microphone open while held", () => {
    useVoiceCallStore.setState({ pushToTalk: true });
    const pressToTalk = vi.fn();
    render(<View session={fake(live(), { pressToTalk })} />);
    expect(screen.getByText(/Push to talk is on/)).toBeInTheDocument();
    expect(screen.getAllByText("Hold to talk").length).toBeGreaterThan(0);
    const hold = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(hold);
    expect(pressToTalk).toHaveBeenCalledWith(true);
    expect(screen.getByText("Talking · release to send")).toBeInTheDocument();
    fireEvent.pointerUp(hold);
    expect(pressToTalk).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole("button", { name: "Push to talk" }));
    expect(useVoiceCallStore.getState().pushToTalk).toBe(false);
  });

  it("mutes through the session", () => {
    const setMuted = vi.fn();
    render(<View session={fake(live(), { setMuted })} />);
    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(setMuted).toHaveBeenCalledWith(true);
  });

  it.each([
    ["time_limit", /Time limit reached/],
    ["budget", /The budget has run out/],
    ["minutes", /This month's call minutes are used up/],
  ])("says a %s limit is ending the call while the agent says so", (kind, text) => {
    render(<View session={fake(live(frame({ type: "notice", kind })))} />);
    expect(screen.getByTestId("dictation-strip-text")).toHaveTextContent(text);
  });

  it("sums up a call ended by its limit, with the minutes left", () => {
    const onCallAgain = vi.fn();
    render(
      <View session={fake((STATES.limitend as () => CallState)())} onCallAgain={onCallAgain} />,
    );
    expect(screen.getByText(/No turns were saved/)).toHaveTextContent(
      "Your organization has 530 voice minutes left this month.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start a new call" }));
    expect(onCallAgain).toHaveBeenCalledOnce();
  });

  it("sums up a reconnect refused for the call's time as the time limit", () => {
    // `call_limit`: the call had used its whole time when it tried to resume.
    render(<View session={fake(live(frame({ type: "ended", reason: "call_limit" })))} />);
    expect(screen.queryByText(/The call ended unexpectedly/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/time limit/i).length).toBeGreaterThan(0);
  });

  it("names a limit or a reason that ended the call in the summary", () => {
    const { rerender } = render(
      <View session={fake(live(frame({ type: "ended", reason: "budget" })))} />,
    );
    expect(screen.getByText("The call ended: the budget ran out")).toBeInTheDocument();
    rerender(<View session={fake(live(frame({ type: "ended", reason: "guardrail" })))} />);
    expect(screen.getByText("The call ended: a guardrail stopped it")).toBeInTheDocument();
    expect(screen.getByText(/0 turns|No turns were saved/)).toBeInTheDocument();
    rerender(<View session={fake(live(frame({ type: "ended", reason: "reaped" })))} />);
    expect(screen.getByText(/^Voice call ended/)).toBeInTheDocument();
  });

  it("counts the turns a call saved, and offers Call again after a drop", () => {
    const onCallAgain = vi.fn();
    const saved = frame({
      type: "turn_saved",
      message: { id: "m", role: "user", content: "Hi.", interrupted: false, turn_id: "t" },
    });
    const { rerender } = render(
      <View session={fake(live(saved, saved, frame({ type: "ended", reason: "user" })))} />,
    );
    expect(screen.getByText(/2 turns saved as messages/)).toBeInTheDocument();
    rerender(
      <View session={fake((STATES.dropped as () => CallState)())} onCallAgain={onCallAgain} />,
    );
    expect(screen.getByText(/The connection was lost/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Call again" }));
    expect(onCallAgain).toHaveBeenCalledOnce();
  });

  it("offers Try again and Dismiss when a call could not start, saying why", () => {
    const dismiss = vi.fn();
    const onCallAgain = vi.fn();
    render(
      <View
        session={fake(drive({ type: "connecting" }, frame({ type: "ended", reason: "busy" })), {
          dismiss,
        })}
        onCallAgain={onCallAgain}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The call didn't start. You're already on a call",
    );
    expect(screen.queryByTestId("voice-captions-visible")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onCallAgain).toHaveBeenCalledOnce();
    expect(dismiss).toHaveBeenCalledOnce();
  });

  it("says nothing more of a call hung up on before it started", () => {
    render(
      <View
        session={fake(drive({ type: "connecting" }, frame({ type: "ended", reason: "user" })))}
      />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status", { name: /ended/ })).toBeNull();
  });

  it.each([
    ["mic_insecure", /This page can't use the microphone/],
    ["mic_not_found", /No microphone found/],
    ["mic_busy", /The microphone didn't start/],
  ] as const)("tells a %s failure how to fix it", (failure, text) => {
    render(<View session={fake(drive({ type: "connecting" }, { type: "mic_failed", failure }))} />);
    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("tells a call whose audio failed mid-call apart from one that never connected", () => {
    render(<View session={fake(live({ type: "media_failed", now: NOW + 5000 }))} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The call's audio couldn't get through");
  });
});

describe("showVoiceApproval", () => {
  it("brings the waiting card into view and puts focus on Approve", () => {
    // In the chat's own scroller: `scrollIntoView` scrolls every scrollable
    // ancestor, and the page column around the chat is one.
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const scroller = document.createElement("div");
    scroller.style.overflowY = "auto";
    Object.defineProperty(scroller, "clientHeight", { get: () => 400 });
    scroller.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
    const scrollTo = vi.fn();
    scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo;
    document.body.append(scroller);
    const below = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ top: 1000, bottom: 1300, height: 300 } as DOMRect);
    render(<View session={fake(live(frame(APPROVAL)))} />, { container: scroller });
    act(() => showVoiceApproval());
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 950, behavior: "smooth" });
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
    below.mockRestore();
    scroller.remove();
    delete (Element.prototype as Partial<Element>).scrollIntoView;
  });

  it("does nothing when no card waits", () => {
    expect(() => showVoiceApproval()).not.toThrow();
  });
});
