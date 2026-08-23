/**
 * Types for the seeded trigger templates - ready-made starting points, so a
 * first trigger is a pick rather than a blank box.
 *
 * Mirrors the backend's `/trigger-templates` catalog. Each template carries a
 * prompt plus the mode that decides which create flow offers it: a schedule
 * template a suggested cadence (the same interval-or-cron shape a `Trigger`
 * uses), an event template the source whose message step offers it. Picking one
 * prefills what its mode can use and nothing else.
 */

import type { EventSource, ScheduleKind, TriggerType } from "@/types/triggers";

/** A schedule template's suggested cadence - one of the two disjoint shapes. */
export interface TriggerTemplateCadence {
  schedule_kind: ScheduleKind;
  interval_seconds?: number | null;
  cron_expression?: string | null;
}

export interface TriggerTemplate {
  key: string;
  label: string;
  description: string;
  prompt: string;
  trigger_type: TriggerType;
  /** Set on a schedule template, absent on an event one. */
  suggested_cadence?: TriggerTemplateCadence | null;
  /** Set on an event template, absent on a schedule one. */
  event_source?: EventSource | null;
}

export interface TriggerTemplateList {
  items: TriggerTemplate[];
  total: number;
}
