/**
 * Types for agent exposures - where an agent is available.
 *
 * One concept covers every place an agent can be reached, which is why the
 * Builder shows one section rather than one per channel. Today that is a Slack
 * or Telegram bot; the shape is the same when a surface with its own auth is
 * added, because a surface is a row here and not a field on the spec.
 */

import type { UsageReporting } from "@/types/channels";

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
  /**
   * Added to the agent's instructions on this binding only - how to lay a
   * message out here, how to give a link, how long an answer should be.
   *
   * Appended rather than substituted, so a surface can shape an answer and
   * never contradict what the agent is for.
   */
  prompt: string | null;
  /**
   * Which channel lookups the agent may make *here*, by tool id.
   *
   * Per bound bot rather than per agent: one agent can answer on an internal
   * Mattermost and a customer Slack, and "may it read what was said in this
   * channel" is a different answer on each. Empty is what a new binding starts
   * as and grants none of them.
   */
  tools: string[];
  /**
   * What this binding's platform can actually answer, resolved server-side.
   *
   * Telegram gives a bot no channel search and no way to read history, so the
   * form offers a control only where there is something behind it - a checkbox
   * whose only effect is a tool that refuses is a worse answer than no
   * checkbox. The name and description are the registry's own, so the sentence
   * somebody reads while deciding to grant a tool is the one the model reads
   * before deciding to call it.
   */
  available_tools: ExposureTool[];
  /**
   * How talkative the agent is here about what a turn cost.
   *
   * On the binding rather than on the bot, where it used to sit: whether an
   * answer carries a cost footer is part of what this agent says on this
   * surface, and on the bot it was an operator's setting in a table of tokens
   * and addresses.
   */
  usage_reporting: UsageReporting;
  is_active: boolean;
  created_at: string | null;
}

/** One channel lookup, as the binding's form offers it. */
export interface ExposureTool {
  id: string;
  name: string;
  description: string;
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
