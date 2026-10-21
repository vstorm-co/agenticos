/**
 * Voice conversations on the wire (#54) - the mirror of
 * `backend/app/schemas/voice.py`: readiness, the socket's frames both ways and
 * the realtime catalog.
 */

import type { AskUserAnswer } from "./chat";
import type { WireQuestion } from "./runs";

export type VoiceTransport = "webrtc" | "relay";

/** Where a call comes from: `/chat`, or a widget or hosted page. */
export type VoiceCallSurface = "web" | "embed";

/** Who is talking, or what the agent is doing - the server's `state` frame. */
export type VoiceActivity =
  | "connecting"
  | "listening"
  | "user_speaking"
  | "thinking"
  | "agent_speaking"
  | "interrupted"
  | "tool_running"
  | "awaiting_approval";

/** Why a call ended: how a live call stopped, or why one was refused at setup. */
export type VoiceEndReason =
  | "user"
  | "time_limit"
  // A reconnect refused because the call had used its whole time.
  | "call_limit"
  | "budget"
  | "disconnected"
  | "revoked"
  | "guardrail"
  | "error"
  | "shutdown"
  | "reaped"
  | "no_agent"
  | "forbidden"
  | "not_configured"
  | "bad_offer"
  | "data_channel"
  | "resume_refused"
  | "not_priced"
  | "busy"
  | "line_busy"
  | "no_start"
  // What a visitor is told for any refusal or end that is the operator's to
  // know about - budget, a missing price or setup (`session.py`).
  | "unavailable";

/** Why the call button is crossed out. */
export type VoiceUnavailable = "no_voice" | "not_offered" | "no_key";

/** `GET /agents/{id}/voice`: whether a call to this agent would start, and why not. */
export interface VoiceReadiness {
  available: boolean;
  unavailable: VoiceUnavailable | null;
  transport: VoiceTransport | null;
  provider: string | null;
  model: string | null;
  /** The longest this call could run: the agent's longest call. */
  cap_seconds: number;
}

/** A finished turn, as the message it was saved as. */
export interface VoiceSavedTurn {
  id: string;
  role: string;
  content: string;
  interrupted: boolean;
  turn_id: string | null;
}

/** Every JSON frame the server sends on the voice socket. */
export type VoiceServerFrame =
  | { type: "answer"; sdp: string }
  | {
      type: "ready";
      call_id: string;
      /** The call's run; left out for a visitor, as a text embed does. */
      run_id?: string;
      conversation_id: string;
      transport: VoiceTransport;
      input_sample_rate: number;
      output_sample_rate: number;
      cap_seconds: number;
      /** What a reconnect of this connection sends as `start.resume_token`; only this caller gets it. */
      resume_token: string;
    }
  | { type: "state"; state: VoiceActivity }
  | {
      type: "caption";
      role: "user" | "assistant";
      /** The `turn_id` of the message this part is saved in; `turn_saved` replaces it. */
      turn_id: string;
      /** Which speech part of the turn - the agent's parts in one response share a turn. */
      part: number;
      /** Words to append. */
      delta?: string | null;
      /** The screened caption so far, replacing the part's (an output guardrail's sentences). */
      text?: string | null;
      /** The finished, screened part. */
      final?: string | null;
    }
  | { type: "tool"; name: string; status: "running" | "done" }
  | { type: "turn_saved"; message: VoiceSavedTurn }
  | {
      type: "approval_required";
      id: string;
      tool: string;
      args: Record<string, unknown>;
      said: string | null;
      timeout_seconds: number;
    }
  | { type: "approval_unavailable"; tool: string; args: Record<string, unknown> }
  | { type: "approval_settled"; id: string; outcome: "approved" | "denied" | "expired" }
  /** Questions the agent waits on - the chat's card; a tap or the caller's words answer it. */
  | { type: "questions"; id: string; questions: WireQuestion[]; timeout_seconds: number }
  | { type: "questions_settled"; id: string }
  | { type: "notice"; kind: string; message?: string | null }
  | { type: "limit"; seconds_left: number }
  | { type: "ended"; reason: VoiceEndReason; message?: string | null }
  | { type: "clear_playback" };

/** What an embed's page says about its visitor, as a text message's `context` carries it. */
export type VoiceStartContext = Record<string, string | number | boolean | null>;

/** Every JSON frame this page sends on the voice socket. */
export type VoiceClientFrame =
  | {
      type: "start";
      agent_id?: string;
      conversation_id?: string | null;
      sdp_offer?: string;
      resume_of?: string;
      /** With `resume_of`: that connection's `ready.resume_token`; a resume without it is refused. */
      resume_token?: string;
      /** An embed's call only: the page's supplied variables (`StartFrame.context`). */
      context?: VoiceStartContext;
    }
  | { type: "approval"; id: string; decision: "approve" | "deny" }
  | { type: "answers"; id: string; answers: AskUserAnswer[] }
  | { type: "mute"; muted: boolean }
  | { type: "end" }
  | { type: "played"; bytes: number };

/** One realtime model a Voice section may pick. */
export interface RealtimeModel {
  id: string;
  name: string;
  description: string;
  transport: VoiceTransport;
  voices: string[];
  default_voice: string;
  supports_thinking: boolean;
  input_sample_rate: number;
  output_sample_rate: number;
}

/** A provider that can hold a voice conversation, and the vault kind its key must be. */
export interface RealtimeProvider {
  provider: string;
  name: string;
  secret_kind: "api_key" | "azure_openai";
  /** Azure: calls go to a named deployment, which runs one of `models`. */
  deployment: boolean;
  models: RealtimeModel[];
}

/** One agent's call time over a usage window; no id and no name for agents since deleted. */
export interface VoiceAgentMinutes {
  agent_id: string | null;
  agent_name: string | null;
  seconds: number;
  /** Calls started; a reconnect is part of the call it resumed. */
  calls: number;
}

/** Call time over a window, by agent. */
export interface VoiceUsage {
  /** The window, as instants: calls started at or after `start` and before `end`. */
  start: string;
  end: string;
  seconds: number;
  calls: number;
  /** Most seconds first; deleted agents' calls together in one row. */
  by_agent: VoiceAgentMinutes[];
}
