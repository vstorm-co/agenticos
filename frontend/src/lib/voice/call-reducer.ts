import type { MicFailure } from "@/hooks/use-dictation";
import type {
  VoiceActivity,
  VoiceEndReason,
  VoiceServerFrame,
  VoiceTransport,
} from "@/types/voice";

import { applyCaption, applySavedTurn, type Caption } from "./captions";

export type { MicFailure };

/** Which of the designed states a call view shows (the mockups' fourteen, plus a reconnect and a drop). */
export type VoiceViewState =
  | "connecting"
  | "listening"
  | "user"
  | "thinking"
  | "agent"
  | "interrupted"
  | "tool"
  | "approval"
  | "noapproval"
  | "limitwarn"
  | "limitend"
  | "ended"
  | "micblocked"
  | "connfailed"
  | "reconnecting"
  | "dropped";

export interface PendingVoiceApproval {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  said: string | null;
  /** When the server denies it unanswered, in this page's clock (ms). */
  deadline: number;
  /** How long the server gives a decision, as the frame said - the countdown's whole length. */
  timeoutSeconds: number;
}

/** An approval the call has settled, kept on screen as the record until the next turn lands. */
export interface SettledVoiceApproval {
  approval: PendingVoiceApproval;
  outcome: "approved" | "denied" | "expired";
}

export interface CallState {
  phase: "idle" | "connecting" | "live" | "reconnecting" | "ended";
  activity: VoiceActivity;
  callId: string | null;
  runId: string | null;
  conversationId: string | null;
  transport: VoiceTransport | null;
  capSeconds: number | null;
  minutesLeft: number | null;
  /** When the first connection of the call went live; a reconnect keeps it. */
  startedAt: number | null;
  warningSecondsLeft: number | null;
  /** When the warning arrived, in this page's clock (ms), so its countdown runs from it. */
  warningAt: number | null;
  captions: Caption[];
  approval: PendingVoiceApproval | null;
  settled: SettledVoiceApproval | null;
  approvalUnavailable: { tool: string; args: Record<string, unknown> } | null;
  tool: string | null;
  notice: string | null;
  endReason: VoiceEndReason | null;
  endMessage: string | null;
  failure: MicFailure | "connection_failed" | null;
  muted: boolean;
  /** Turns saved as messages over the whole call, reconnects included. */
  savedTurns: number;
  /** When the call ended, in this page's clock (ms). */
  endedAt: number | null;
}

export type CallAction =
  | { type: "connecting" }
  | { type: "frame"; frame: VoiceServerFrame; now: number }
  | { type: "mic_failed"; failure: MicFailure }
  | { type: "socket_lost"; willRetry: boolean }
  | { type: "media_failed"; now: number }
  | { type: "muted"; muted: boolean }
  | { type: "dismiss_unavailable" }
  | { type: "reset" };

/** The reasons a call ends because a limit ran out, shown apart from an ordinary end. */
export const LIMIT_REASONS: ReadonlySet<VoiceEndReason> = new Set<VoiceEndReason>([
  "time_limit",
  "budget",
  "minutes",
  "minutes_exhausted",
]);

export const initialCall: CallState = {
  phase: "idle",
  activity: "connecting",
  callId: null,
  runId: null,
  conversationId: null,
  transport: null,
  capSeconds: null,
  minutesLeft: null,
  startedAt: null,
  warningSecondsLeft: null,
  warningAt: null,
  captions: [],
  approval: null,
  settled: null,
  approvalUnavailable: null,
  tool: null,
  notice: null,
  endReason: null,
  endMessage: null,
  failure: null,
  muted: false,
  savedTurns: 0,
  endedAt: null,
};

function onFrame(state: CallState, frame: VoiceServerFrame, now: number): CallState {
  switch (frame.type) {
    case "ready": {
      // A resumed connection's `ready` says what is left of the call: its time
      // is rebased onto the time the call has run, and its minutes stay the
      // ones the call started with, which the summary takes the call's off.
      const resumed = state.startedAt !== null;
      return {
        ...state,
        phase: "live",
        activity: "listening",
        callId: frame.call_id,
        runId: frame.run_id ?? null,
        conversationId: frame.conversation_id,
        transport: frame.transport,
        capSeconds: resumed
          ? Math.round((now - (state.startedAt as number)) / 1000) + frame.cap_seconds
          : frame.cap_seconds,
        minutesLeft: resumed ? state.minutesLeft : frame.minutes_left,
        startedAt: state.startedAt ?? now,
        failure: null,
      };
    }
    case "state":
      return {
        ...state,
        activity: frame.state,
        tool: frame.state === "tool_running" ? state.tool : null,
      };
    case "caption":
      return { ...state, captions: applyCaption(state.captions, frame) };
    case "turn_saved":
      // The settled card was the record until the transcript could hold it.
      return {
        ...state,
        captions: applySavedTurn(state.captions, frame.message),
        savedTurns: state.savedTurns + 1,
        settled: null,
      };
    case "tool":
      return { ...state, tool: frame.status === "running" ? frame.name : null };
    case "approval_required":
      return {
        ...state,
        activity: "awaiting_approval",
        approval: {
          id: frame.id,
          tool: frame.tool,
          args: frame.args,
          said: frame.said,
          deadline: now + frame.timeout_seconds * 1000,
          timeoutSeconds: frame.timeout_seconds,
        },
      };
    case "approval_unavailable":
      return { ...state, approvalUnavailable: { tool: frame.tool, args: frame.args } };
    case "approval_settled":
      return state.approval?.id === frame.id
        ? {
            ...state,
            approval: null,
            settled: { approval: state.approval, outcome: frame.outcome },
          }
        : state;
    case "notice":
      return { ...state, notice: frame.kind };
    case "limit":
      return { ...state, warningSecondsLeft: frame.seconds_left, warningAt: now };
    case "ended":
      // The server's answer to an End the page already put away - a new chat,
      // another conversation - brings back no summary over what is open now.
      if (state.phase === "idle") return state;
      return {
        ...state,
        phase: "ended",
        endReason: frame.reason,
        endMessage: frame.message ?? null,
        endedAt: state.endedAt ?? now,
        approval: null,
        settled: null,
      };
    default:
      // `answer` and `clear_playback` are the media's.
      return state;
  }
}

/**
 * The call's state machine (#54): what the socket said, and what happened to
 * the microphone and the connection, folded into one view state.
 */
export function callReducer(state: CallState, action: CallAction): CallState {
  switch (action.type) {
    case "connecting":
      // A new call: nothing of the last one carries over. A reconnect never
      // passes through here - it keeps its captions and its start through
      // `socket_lost` and the next `ready`.
      return { ...initialCall, phase: "connecting" };
    case "frame":
      return onFrame(state, action.frame, action.now);
    case "mic_failed":
      return { ...initialCall, phase: "ended", failure: action.failure };
    case "socket_lost":
      if (state.phase === "ended") return state;
      if (action.willRetry) return { ...state, phase: "reconnecting", approval: null };
      return {
        ...state,
        phase: "ended",
        failure: state.phase === "connecting" ? "connection_failed" : null,
        endReason: state.phase === "connecting" ? null : "disconnected",
      };
    case "media_failed":
      // The peer connection itself failed - a network that lets the socket
      // through but blocks the audio. The call is over, whatever the socket says.
      return {
        ...state,
        phase: "ended",
        failure: "connection_failed",
        endedAt: state.endedAt ?? action.now,
        approval: null,
        settled: null,
      };
    case "muted":
      return { ...state, muted: action.muted };
    case "dismiss_unavailable":
      return { ...state, approvalUnavailable: null };
    case "reset":
      return initialCall;
  }
}

const ACTIVITY_VIEW: Record<VoiceActivity, VoiceViewState> = {
  connecting: "connecting",
  listening: "listening",
  user_speaking: "user",
  thinking: "thinking",
  agent_speaking: "agent",
  interrupted: "interrupted",
  tool_running: "tool",
  awaiting_approval: "approval",
};

/** Which of the designed states the view shows. */
export function viewState(call: CallState): VoiceViewState {
  if (call.failure === "connection_failed") return "connfailed";
  if (call.failure !== null) return "micblocked";
  if (call.phase === "reconnecting") return "reconnecting";
  if (call.phase === "ended") {
    if (call.endReason === "disconnected") return "dropped";
    return call.endReason !== null && LIMIT_REASONS.has(call.endReason) ? "limitend" : "ended";
  }
  if (call.phase === "connecting" || call.phase === "idle") return "connecting";
  if (call.approvalUnavailable !== null) return "noapproval";
  if (call.approval !== null) return "approval";
  if (call.warningSecondsLeft !== null && call.activity === "listening") return "limitwarn";
  return ACTIVITY_VIEW[call.activity];
}
