import { describe, expect, it } from "vitest";

import { callReducer, initialCall, viewState, type CallState } from "./call-reducer";

const ready = {
  type: "ready",
  call_id: "c1",
  run_id: "r1",
  conversation_id: "conv1",
  transport: "webrtc",
  input_sample_rate: 24000,
  output_sample_rate: 24000,
  cap_seconds: 600,
  resume_token: "tok1",
} as const;

function live(): CallState {
  const connecting = callReducer(initialCall, { type: "connecting" });
  return callReducer(connecting, { type: "frame", frame: ready, now: 1000 });
}

describe("callReducer", () => {
  it("goes from connecting to listening when the call is ready", () => {
    expect(viewState(initialCall)).toBe("connecting");
    expect(viewState(callReducer(initialCall, { type: "connecting" }))).toBe("connecting");
    const call = live();
    expect(call.phase).toBe("live");
    expect(call.callId).toBe("c1");
    expect(call.startedAt).toBe(1000);
    expect(viewState(call)).toBe("listening");
  });

  it("holds no run for a visitor's call, whose ready names none", () => {
    const { run_id: _run, ...visitors } = ready;
    const connecting = callReducer(initialCall, { type: "connecting" });
    const call = callReducer(connecting, { type: "frame", frame: visitors, now: 1000 });
    expect(call.runId).toBeNull();
    expect(call.callId).toBe("c1");
  });

  it.each([
    ["user_speaking", "user"],
    ["thinking", "thinking"],
    ["agent_speaking", "agent"],
    ["interrupted", "interrupted"],
    ["tool_running", "tool"],
    ["awaiting_approval", "approval"],
    ["connecting", "connecting"],
  ] as const)("shows %s as %s", (state, view) => {
    expect(
      viewState(callReducer(live(), { type: "frame", frame: { type: "state", state }, now: 2000 })),
    ).toBe(view);
  });

  it("names the tool running and forgets it once the agent moves on", () => {
    const running = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "tool", name: "web_search", status: "running" },
    });
    expect(running.tool).toBe("web_search");
    const stillRunning = callReducer(running, {
      type: "frame",
      now: 2,
      frame: { type: "state", state: "tool_running" },
    });
    expect(stillRunning.tool).toBe("web_search");
    const done = callReducer(running, {
      type: "frame",
      now: 3,
      frame: { type: "tool", name: "web_search", status: "done" },
    });
    expect(done.tool).toBeNull();
    const spoke = callReducer(running, {
      type: "frame",
      now: 4,
      frame: { type: "state", state: "agent_speaking" },
    });
    expect(spoke.tool).toBeNull();
  });

  it("holds an approval with its deadline until it is settled", () => {
    const asked = callReducer(live(), {
      type: "frame",
      now: 5000,
      frame: {
        type: "approval_required",
        id: "a1",
        tool: "send_invoice",
        args: { customer: "Ahmad", amount_eur: 120 },
        said: "send an invoice for 120 euros to Ahmad",
        timeout_seconds: 60,
      },
    });
    expect(asked.approval).toEqual({
      id: "a1",
      tool: "send_invoice",
      args: { customer: "Ahmad", amount_eur: 120 },
      said: "send an invoice for 120 euros to Ahmad",
      deadline: 65_000,
      timeoutSeconds: 60,
    });
    expect(viewState(asked)).toBe("approval");
    const other = callReducer(asked, {
      type: "frame",
      now: 6000,
      frame: { type: "approval_settled", id: "a2", outcome: "approved" },
    });
    expect(other).toBe(asked);
    const settled = callReducer(asked, {
      type: "frame",
      now: 6000,
      frame: { type: "approval_settled", id: "a1", outcome: "denied" },
    });
    expect(settled.approval).toBeNull();
    // Kept as the record of what was decided until the next turn lands.
    expect(settled.settled).toEqual({ approval: asked.approval, outcome: "denied" });
    const next = callReducer(settled, {
      type: "frame",
      now: 7000,
      frame: {
        type: "turn_saved",
        message: { id: "m", role: "assistant", content: "Okay.", interrupted: false, turn_id: "t" },
      },
    });
    expect(next.settled).toBeNull();
    expect(next.savedTurns).toBe(1);
  });

  it("holds the questions card until it settles, and drops it when the call drops", () => {
    const questions = [
      { question: "Which size?", header: "Size", options: [], allow_custom: true },
    ];
    const asked = callReducer(live(), {
      type: "frame",
      now: 5000,
      frame: { type: "questions", id: "q1", questions, timeout_seconds: 120 },
    });
    expect(asked.questions).toEqual({ id: "q1", questions });
    const other = callReducer(asked, {
      type: "frame",
      now: 6000,
      frame: { type: "questions_settled", id: "q2" },
    });
    expect(other).toBe(asked);
    const answered = callReducer(asked, {
      type: "frame",
      now: 6000,
      frame: { type: "questions_settled", id: "q1" },
    });
    expect(answered.questions).toBeNull();
    for (const action of [
      { type: "socket_lost", willRetry: true } as const,
      { type: "media_failed", now: 7000 } as const,
      { type: "frame", now: 7000, frame: { type: "ended", reason: "user" } } as const,
    ]) {
      expect(callReducer(asked, action).questions).toBeNull();
    }
  });

  it("drops a pending and a settled approval when the call ends, and keeps the first end time", () => {
    const asked = callReducer(live(), {
      type: "frame",
      now: 5000,
      frame: {
        type: "approval_required",
        id: "a1",
        tool: "send_invoice",
        args: {},
        said: null,
        timeout_seconds: 60,
      },
    });
    const ended = callReducer(asked, {
      type: "frame",
      now: 8000,
      frame: { type: "ended", reason: "user" },
    });
    expect(ended.approval).toBeNull();
    expect(ended.settled).toBeNull();
    expect(ended.endedAt).toBe(8000);
    // The server's own account of the end arrives after the button press.
    const confirmed = callReducer(ended, {
      type: "frame",
      now: 9000,
      frame: { type: "ended", reason: "user" },
    });
    expect(confirmed.endedAt).toBe(8000);
  });

  it("shows an approval this caller cannot give, until it is dismissed", () => {
    const call = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "approval_unavailable", tool: "send_invoice", args: {} },
    });
    expect(viewState(call)).toBe("noapproval");
    expect(viewState(callReducer(call, { type: "dismiss_unavailable" }))).toBe("listening");
  });

  it("keeps the last notice and whether the microphone is muted", () => {
    const noticed = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "notice", kind: "guardrail" },
    });
    expect(noticed.notice).toBe("guardrail");
    expect(callReducer(noticed, { type: "muted", muted: true }).muted).toBe(true);
  });

  it("ignores frames the call view has no use for", () => {
    const call = live();
    expect(callReducer(call, { type: "frame", now: 1, frame: { type: "answer", sdp: "x" } })).toBe(
      call,
    );
    expect(callReducer(call, { type: "frame", now: 1, frame: { type: "clear_playback" } })).toBe(
      call,
    );
  });

  it("puts a saved turn in place of its caption", () => {
    const captioned = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "caption", role: "user", turn_id: "t", part: 0, delta: "hi the" },
    });
    const saved = callReducer(captioned, {
      type: "frame",
      now: 2,
      frame: {
        type: "turn_saved",
        message: { id: "m", role: "user", content: "Hi there.", interrupted: false, turn_id: "t" },
      },
    });
    expect(saved.captions).toEqual([
      { turnId: "t", part: 0, role: "user", text: "Hi there.", final: true },
    ]);
  });

  it("warns near the limit and tells a limit end from an ordinary one", () => {
    const warned = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "limit", seconds_left: 60 },
    });
    expect(viewState(warned)).toBe("limitwarn");
    expect(warned.warningAt).toBe(1);
    expect(
      viewState(
        callReducer(warned, { type: "frame", now: 1, frame: { type: "state", state: "thinking" } }),
      ),
    ).toBe("thinking");
    const ended = callReducer(warned, {
      type: "frame",
      now: 2,
      frame: { type: "ended", reason: "time_limit", message: "Time is up." },
    });
    expect(viewState(ended)).toBe("limitend");
    expect(ended.endMessage).toBe("Time is up.");
    const byUser = callReducer(live(), {
      type: "frame",
      now: 2,
      frame: { type: "ended", reason: "user" },
    });
    expect(viewState(byUser)).toBe("ended");
    expect(byUser.endMessage).toBeNull();
  });

  it("separates a blocked microphone, a failed connection, a reconnect and a drop", () => {
    expect(viewState(callReducer(initialCall, { type: "mic_failed", failure: "mic_denied" }))).toBe(
      "micblocked",
    );
    expect(
      viewState(
        callReducer(callReducer(initialCall, { type: "connecting" }), {
          type: "socket_lost",
          willRetry: false,
        }),
      ),
    ).toBe("connfailed");
    expect(viewState(callReducer(live(), { type: "socket_lost", willRetry: true }))).toBe(
      "reconnecting",
    );
    expect(viewState(callReducer(live(), { type: "socket_lost", willRetry: false }))).toBe(
      "dropped",
    );
  });

  it("keeps an ended call ended when its socket closes after", () => {
    const ended = callReducer(live(), {
      type: "frame",
      now: 2,
      frame: { type: "ended", reason: "user" },
    });
    expect(callReducer(ended, { type: "socket_lost", willRetry: true })).toBe(ended);
  });

  it("keeps the captions and start of the previous connection through a reconnect", () => {
    const captioned = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "caption", role: "user", turn_id: "t", part: 0, final: "hi" },
    });
    const lost = callReducer(captioned, { type: "socket_lost", willRetry: true });
    const resumed = callReducer(lost, {
      type: "frame",
      now: 9,
      frame: { ...ready, call_id: "c2" },
    });
    expect(resumed.captions).toHaveLength(1);
    expect(resumed.startedAt).toBe(1000);
    expect(resumed.callId).toBe("c2");
  });

  it("keeps the call's whole time limit through a reconnect", () => {
    // Five minutes into a ten-minute call, the resumed connection's `ready` says
    // what is left: the bar must not read 5:00 / 5:00.
    const lost = callReducer(live(), { type: "socket_lost", willRetry: true });
    const resumed = callReducer(lost, {
      type: "frame",
      now: 1000 + 300_000,
      frame: { ...ready, call_id: "c2", cap_seconds: 300 },
    });

    expect(resumed.capSeconds).toBe(600);
  });

  it("starts a new call from nothing, captions and clock included", () => {
    const captioned = callReducer(live(), {
      type: "frame",
      now: 1,
      frame: { type: "caption", role: "user", turn_id: "t", part: 0, final: "hi" },
    });
    const ended = callReducer(captioned, {
      type: "frame",
      now: 2,
      frame: { type: "ended", reason: "user" },
    });
    expect(callReducer(ended, { type: "connecting" })).toEqual({
      ...initialCall,
      phase: "connecting",
    });
  });

  it("ends a call whose audio failed as a failed connection, keeping when it ran", () => {
    const failed = callReducer(live(), { type: "media_failed", now: 9000 });
    expect(failed.phase).toBe("ended");
    expect(failed.startedAt).toBe(1000);
    expect(failed.endedAt).toBe(9000);
    expect(viewState(failed)).toBe("connfailed");
  });

  it("brings back no ended call the page already put away", () => {
    // New chat during a call: End, then dismiss - and the server's answer to the
    // End arrives after, onto an idle page.
    const dismissed = callReducer(live(), { type: "reset" });
    const late = callReducer(dismissed, {
      type: "frame",
      frame: { type: "ended", reason: "user" },
      now: 9000,
    });
    expect(late).toBe(initialCall);
  });

  it("forgets everything on reset", () => {
    expect(callReducer(live(), { type: "reset" })).toBe(initialCall);
  });
});
