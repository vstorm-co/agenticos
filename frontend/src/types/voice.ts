/**
 * Voice conversations on the wire (#54) - the mirror of
 * `backend/app/schemas/voice.py`: readiness, the socket's frames both ways and
 * the realtime catalog.
 */

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
  | "budget"
  | "minutes"
  | "disconnected"
  | "revoked"
  | "guardrail"
  | "error"
  | "shutdown"
  | "reaped"
  | "voice_off"
  | "no_agent"
  | "forbidden"
  | "not_configured"
  | "bad_offer"
  | "data_channel"
  | "resume_refused"
  | "minutes_exhausted"
  | "not_priced"
  | "busy"
  | "line_busy"
  | "no_start";

/** Why the call button is crossed out. */
export type VoiceUnavailable =
  "org_off" | "not_in_chat" | "no_voice" | "not_offered" | "no_key" | "minutes_exhausted";

/** `GET /agents/{id}/voice`: whether a call to this agent would start, and why not. */
export interface VoiceReadiness {
  available: boolean;
  unavailable: VoiceUnavailable | null;
  transport: VoiceTransport | null;
  provider: string | null;
  model: string | null;
  /** The longest this call could run, after the minutes left. */
  cap_seconds: number;
  /** This month's remaining call minutes; null when only the budgets bound calls. */
  minutes_left: number | null;
  /** Capabilities of this agent a call cannot use. */
  unavailable_capabilities: string[];
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
      run_id: string;
      conversation_id: string;
      transport: VoiceTransport;
      input_sample_rate: number;
      output_sample_rate: number;
      cap_seconds: number;
      minutes_left: number | null;
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
  | { type: "notice"; kind: string; message?: string | null }
  | { type: "limit"; seconds_left: number }
  | { type: "ended"; reason: VoiceEndReason; message?: string | null }
  | { type: "clear_playback" };

/** Every JSON frame this page sends on the voice socket. */
export type VoiceClientFrame =
  | {
      type: "start";
      agent_id?: string;
      conversation_id?: string | null;
      sdp_offer?: string;
      resume_of?: string;
    }
  | { type: "approval"; id: string; decision: "approve" | "deny" }
  | { type: "ptt"; state: "down" | "up" }
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
