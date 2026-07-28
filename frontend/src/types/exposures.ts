/**
 * Types for agent exposures - where an agent is available.
 *
 * One concept covers every place an agent can be reached, which is why the
 * Builder shows one section rather than one per channel. Today that is a Slack
 * or Telegram bot; the shape is the same when a surface with its own auth is
 * added, because a surface is a row here and not a field on the spec.
 */

/** A place an agent can be made available. Mirrors the backend's ExposureSurface. */
export type ExposureSurface = "slack" | "telegram" | "mattermost";

/**
 * What one binding may spend, metered against its own runs and nobody else's.
 *
 * Two limits because they fail differently: a monthly cap stops a slow leak,
 * and only a per-run cap stops one adversarial prompt driving a loop - nothing
 * that counts requests can see cost. Strings, not numbers: these are money, and
 * a float is how a cap of 0.1 becomes 0.10000000000000001 on its way back.
 */
export interface ExposureBudget {
  max_per_run_usd: string | null;
  monthly_usd: string | null;
}

export interface Exposure extends ExposureBudget {
  id: string;
  agent_id: string;
  surface: ExposureSurface;
  channel_bot_id: string;
  /** Resolved server-side, so the section can name a place without reading bots. */
  channel_bot_name: string;
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
