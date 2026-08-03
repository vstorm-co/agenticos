/**
 * Types for agent exposures - where an agent is available.
 *
 * One concept covers every place an agent can be reached, which is why the
 * Builder shows one section rather than one per channel. Today that is a Slack
 * or Telegram bot; the shape is the same when a surface with its own auth is
 * added, because a surface is a row here and not a field on the spec.
 */

/** Who shares a workspace. Mirrors the backend's `SessionScope`. */
export type SessionScope = "run" | "conversation" | "channel" | "user" | "agent";

/** A place an agent can be made available. Mirrors the backend's ExposureSurface. */
export type ExposureSurface = "slack" | "telegram" | "mattermost";

export interface Exposure {
  id: string;
  agent_id: string;
  surface: ExposureSurface;
  channel_bot_id: string;
  /** Resolved server-side, so the section can name a place without reading bots. */
  channel_bot_name: string;
  /** Which named environment answers here; null = the default. */
  environment_id: string | null;
  /**
   * Who shares a workspace on *this* surface; null = whatever the spec says.
   *
   * A web chat and a Slack channel are not the same sharing question - one has
   * an account and a conversation, the other has a channel with threads in it -
   * and one value for both was the wrong shape. The spec keeps the default; the
   * binding that admits a run may say something else.
   */
  session_scope: SessionScope | null;
  is_active: boolean;
  created_at: string | null;
}

export interface ExposureList {
  items: Exposure[];
  total: number;
}

/** A bot this agent could be bound to. */
export interface ExposureTarget {
  id: string;
  platform: ExposureSurface;
  name: string;
  is_active: boolean;
}

export interface ExposureTargetList {
  items: ExposureTarget[];
  total: number;
}
