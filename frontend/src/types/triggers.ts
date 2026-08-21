/**
 * Types for agent triggers - when an agent runs with nobody at the keyboard.
 *
 * One table, two concepts, mirroring the backend's `AgentTrigger`. A **schedule**
 * fires on the clock (an interval, or a cron expression in UTC); an **event** fires
 * on an arrival (a GitHub issue, an inbound email) delivered as a signed webhook.
 * `trigger_type` tells them apart, and the fields each uses are disjoint - the same
 * split the shape CHECK enforces server-side.
 */

/** Which of the two concepts a trigger is. Mirrors the backend's `TriggerType`. */
export type TriggerType = "schedule" | "event";

/** How a schedule decides it is due. Mirrors the backend's `ScheduleKind`. */
export type ScheduleKind = "interval" | "cron";

/** Where an event trigger's fire comes from. Mirrors the backend's `EventSource`. */
export type EventSource = "github" | "gmail" | "webhook";

export interface Trigger {
  id: string;
  agent_id: string;
  /** Set only on the org-wide listing, where a row is shown away from its agent. */
  agent_name: string | null;
  /** With the two below, lets that listing draw the agent's avatar, not just name it. */
  agent_has_avatar?: boolean;
  agent_avatar_color?: number | null;
  /** A human title for this trigger; null lists it by the agent's name instead. */
  name: string | null;
  created_by_user_id: string | null;
  is_active: boolean;
  /**
   * Whether *this* caller may edit, pause, run-now or delete this trigger. The
   * server resolves it per row from the caller's grants, so a Viewer holding an
   * explicit run grant on one agent gets it on that agent's triggers and not the
   * rest - which a role-level check on the client could never tell apart. Every
   * trigger read carries it; the per-row controls gate on it rather than on a
   * role.
   */
  can_manage: boolean;
  /** Which named environment answers here; null = the default. */
  environment_id: string | null;
  trigger_type: TriggerType;
  schedule_kind: ScheduleKind;
  interval_seconds: number | null;
  cron_expression: string | null;
  event_source: EventSource | null;
  /** The per-source filter (which actions, which sender); `{}` on a schedule. */
  event_config: Record<string, unknown>;
  prompt: string;
  /** Null on an event trigger, which has no scheduled next fire. */
  next_fire_at: string | null;
  last_fired_at: string | null;
  last_run_id: string | null;
  /** The one run-log conversation every fire appends to, opened eagerly on create. */
  conversation_id: string | null;
  /**
   * Where a provider must deliver, under the deployment's origin; null for a
   * schedule. Derived server-side from the source and id - the secret that
   * authenticates a delivery is never part of it.
   */
  webhook_url: string | null;
  /**
   * The portal lineage, when this trigger came from a preset. `delivery_mode` is
   * `auto_webhook` when the platform registered the hook and `manual` when the
   * user pastes the URL; null on a schedule and on a raw event trigger. Optional
   * so a partial fixture need not carry them - the live `TriggerRead` always does.
   */
  portal_key?: string | null;
  delivery_mode?: "auto_webhook" | "manual" | "polling" | null;
  connection_id?: string | null;
  /**
   * Where a preset points - a repository, a channel - carried on `TriggerRead` so
   * the preset summary can read "New issue in acme/repo". Null on a schedule, on a
   * manual trigger, and on an auto one with no target chosen.
   */
  provider_target?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TriggerList {
  items: Trigger[];
  total: number;
}

/**
 * A new trigger. `trigger_type` decides which fields are read: a schedule uses
 * `schedule_kind` plus its cadence field; an event uses `event_source`,
 * `event_config` and `event_secret`. The secret is sent once, on create, and never
 * returned - the server seals it and only its ciphertext is stored.
 */
export interface TriggerCreate {
  prompt: string;
  /** An optional title; omit to list the trigger by its agent's name. */
  name?: string | null;
  trigger_type: TriggerType;
  environment_id?: string | null;
  schedule_kind?: ScheduleKind;
  interval_seconds?: number | null;
  cron_expression?: string | null;
  event_source?: EventSource | null;
  event_config?: Record<string, unknown> | null;
  event_secret?: string | null;
  /**
   * The portal preset path. `portal_key` and `preset_key` name a ready-made event;
   * the server fills the source, filter and signing secret from the catalog, so
   * none of the `event_*` fields above are sent with them. `connection_id` is the
   * connected account whose token registers the webhook (auto-delivery portals),
   * and `target` which repository it points at.
   */
  portal_key?: string | null;
  preset_key?: string | null;
  connection_id?: string | null;
  target?: string | null;
}

/**
 * The create endpoint's response: a trigger, plus a reveal-once secret.
 *
 * Mirrors the backend's `TriggerCreateRead` - a `TriggerRead` with `reveal_secret`.
 * The secret is populated exactly once, and only for a **manual**-delivery preset:
 * the platform could not auto-register the webhook, so the user must wire a relay
 * and needs the secret to sign each delivery. It is null for an auto-registered
 * preset, a schedule and a raw trigger, and never appears on any GET or list -
 * which is why it lives on this create-only type and not on `Trigger`.
 */
export interface TriggerCreated extends Trigger {
  reveal_secret?: string | null;
}

/**
 * A partial edit. A schedule's cadence can change in place - a new interval, a new
 * cron, or a switch between the two (`schedule_kind` with its field) - and its
 * title. An event's *filter* is editable too: which deliveries fire is a filter,
 * not a different trigger, and the server revalidates it against the source's
 * own rules exactly as create does. What cannot change is a trigger's *type* (a
 * schedule never becomes an event), or an event's source and secret; the source
 * is remade by deleting and recreating, the secret by rotating.
 */
export interface TriggerUpdate {
  prompt?: string;
  name?: string | null;
  schedule_kind?: ScheduleKind;
  interval_seconds?: number | null;
  cron_expression?: string | null;
  is_active?: boolean;
  environment_id?: string | null;
  event_config?: Record<string, unknown>;
}
