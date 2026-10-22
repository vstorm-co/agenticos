import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { initialCall, type CallState } from "@/lib/voice/call-reducer";

import { VoiceCallStatus } from "./voice-call-status";

const LIVE: CallState = {
  ...initialCall,
  phase: "live",
  activity: "listening",
  startedAt: 0,
  capSeconds: 600,
  callId: "c1",
};

function show(call: CallState, now = 1, { pushToTalk = false, holding = false } = {}) {
  return render(
    <VoiceCallStatus
      call={call}
      now={now}
      agentName="Support"
      pushToTalk={pushToTalk}
      holding={holding}
    />,
  );
}

describe("VoiceCallStatus", () => {
  it("shows the state and the elapsed time against the cap", () => {
    show(LIVE, 65_000);
    expect(screen.getByText("Listening")).toBeInTheDocument();
    expect(screen.getByText("1:05")).toBeInTheDocument();
    expect(screen.getByText(/\/ 10:00/)).toBeInTheDocument();
  });

  it("names the agent while it speaks", () => {
    show({ ...LIVE, activity: "agent_speaking" });
    expect(screen.getByText("Support is speaking")).toBeInTheDocument();
  });

  it("says it is setting up before the call is live, with a working shimmer", () => {
    show({ ...initialCall, phase: "connecting" });
    expect(screen.getByText("Connecting…")).toHaveClass("voice-call-shimmer");
    expect(screen.getByTestId("voice-call-connecting")).toHaveClass("motion-safe:animate-spin");
    expect(screen.getByText("Setting up a secure connection")).toBeInTheDocument();
  });

  it.each([
    [{ holding: true }, false, "Talking · release to send"],
    [{}, true, "Muted"],
    [{ holding: true }, true, "Muted"],
    [{ pushToTalk: true }, false, "Hold to talk"],
  ])(
    "tells a closed or held microphone apart while listening (%o, muted %s)",
    (opts, muted, label) => {
      show({ ...LIVE, muted }, 1, opts);
      expect(screen.getByText(label)).toBeInTheDocument();
    },
  );

  it("names the tool that is running, and its id", () => {
    show({ ...LIVE, activity: "tool_running", tool: "web_search" });
    expect(screen.getByText("Searching the web")).toHaveClass("voice-call-shimmer");
    expect(screen.getByText(/web_search/)).toBeInTheDocument();
  });

  it("says a tool is working before it knows which", () => {
    show({ ...LIVE, activity: "tool_running" });
    expect(screen.getByText("Working…")).toBeInTheDocument();
  });

  it("warns near the limit, in the time and assertively", () => {
    show({ ...LIVE, warningSecondsLeft: 60 }, 540_000);
    expect(screen.getByText("Listening")).toBeInTheDocument();
    expect(screen.getByText(/\/ 10:00/)).toHaveClass("text-warning");
    expect(screen.getByRole("alert")).toHaveTextContent("1 minute left in this call");
  });

  it("says the call is ending when a limit stops it, and why", () => {
    show({ ...LIVE, activity: "agent_speaking", notice: "time_limit" });
    expect(screen.getByText("Ending: time limit reached")).not.toHaveClass("voice-call-shimmer");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This call has reached its time limit. The call is ending.",
    );
  });

  it.each([
    ["guardrail", "A guardrail cut the agent off."],
    ["provider_error", "The voice provider reported an error."],
  ])("says what a %s notice means", (kind, text) => {
    show({ ...LIVE, notice: kind });
    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("leaves a notice it does not know unsaid", () => {
    show({ ...LIVE, notice: "something_new" });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("announces an approval with how long it waits", () => {
    show({
      ...LIVE,
      activity: "awaiting_approval",
      approval: {
        id: "a1",
        tool: "send_invoice",
        args: {},
        said: null,
        deadline: 60_000,
        timeoutSeconds: 60,
      },
    });
    expect(screen.getByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Approval needed for Send Invoice. Approve or deny on screen. It is denied automatically in 60 seconds.",
    );
  });
});
