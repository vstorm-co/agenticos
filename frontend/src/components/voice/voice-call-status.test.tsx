import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initialCall, type CallState } from "@/lib/voice/call-reducer";

import { VoiceCallStatus } from "./voice-call-status";

const LIVE: CallState = {
  ...initialCall,
  phase: "live",
  activity: "listening",
  startedAt: 0,
  capSeconds: 600,
  minutesLeft: 540,
  callId: "c1",
};

function show(call: CallState, now = 1, onCallAgain = vi.fn()) {
  return render(
    <VoiceCallStatus call={call} now={now} agentName="Support" onCallAgain={onCallAgain} />,
  );
}

describe("VoiceCallStatus", () => {
  it("shows the state, the elapsed time against the cap and the minutes left", () => {
    show(LIVE, 65_000);
    expect(screen.getByText("Listening")).toBeInTheDocument();
    expect(screen.getByText("1:05 / 10:00")).toBeInTheDocument();
    expect(screen.getByText("540 min left this month")).toBeInTheDocument();
  });

  it("says nothing of minutes where only the budgets bound calls", () => {
    show({ ...LIVE, minutesLeft: null }, 65_000);
    expect(screen.queryByText(/left this month/)).toBeNull();
  });

  it("names the agent while it speaks", () => {
    show({ ...LIVE, activity: "agent_speaking" });
    expect(screen.getByText("Support is speaking")).toBeInTheDocument();
  });

  it("shows no clock before the call is live", () => {
    show({ ...initialCall, phase: "connecting" });
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(screen.queryByText(/\//)).toBeNull();
  });

  it("announces a limit warning assertively", () => {
    show({ ...LIVE, warningSecondsLeft: 60 }, 540_000);
    expect(screen.getByText("Almost out of time")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("1 minute left in this call");
  });

  it("counts a warning in seconds when it is not a whole minute", () => {
    show({ ...LIVE, warningSecondsLeft: 30 });
    expect(screen.getByRole("alert")).toHaveTextContent("30 seconds left in this call");
  });

  it.each([
    ["guardrail", "A guardrail cut the agent off."],
    ["provider_error", "The voice provider reported an error."],
    ["budget", "The budget has run out. The call is ending."],
  ])("says what a %s notice means", (kind, text) => {
    show({ ...LIVE, notice: kind });
    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("leaves a notice it does not know unsaid", () => {
    show({ ...LIVE, notice: "something_new" });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("offers Call again after a drop", () => {
    const onCallAgain = vi.fn();
    show({ ...LIVE, phase: "ended", endReason: "disconnected" }, 1, onCallAgain);
    expect(screen.getByText("Call dropped")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Call again" }));
    expect(onCallAgain).toHaveBeenCalledOnce();
  });

  it("names the limit that ended a call", () => {
    show({ ...LIVE, phase: "ended", endReason: "budget" });
    expect(screen.getByText("Call ended by a limit")).toBeInTheDocument();
    expect(screen.getByText("The call ended: the budget ran out")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Call again" })).toBeNull();
  });

  it.each([
    ["minutes_exhausted", "The call ended: this month's call minutes are used up"],
    ["no_agent", "This agent can't take your call"],
    ["busy", "You're already on a call"],
    ["user", "The call ended"],
    ["reaped", "The call ended"],
  ] as const)("says why a call ended (%s)", (reason, text) => {
    show({ ...LIVE, phase: "ended", endReason: reason });
    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("tells a blocked microphone apart from a failed connection", () => {
    const { rerender } = show({ ...initialCall, phase: "ended", failure: "mic_denied" });
    expect(screen.getByText("The microphone is blocked")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Allow the microphone for this site");
    rerender(
      <VoiceCallStatus
        call={{ ...initialCall, phase: "ended", failure: "connection_failed" }}
        now={1}
        agentName="S"
        onCallAgain={vi.fn()}
      />,
    );
    expect(screen.getByText("The call could not connect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Call again" })).toBeInTheDocument();
  });
});
