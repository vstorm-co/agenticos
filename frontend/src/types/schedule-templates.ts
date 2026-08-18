/**
 * Types for the seeded schedule templates - ready-made "what an agent could do on
 * a clock" starting points, so a first schedule is a pick rather than a blank box.
 *
 * Mirrors the backend's `/schedule-templates` catalog: each template carries a
 * prompt and a suggested cadence, and picking one prefills both. The cadence is
 * the same interval-or-cron shape a `Trigger` uses, so it drops straight into the
 * create form.
 */

import type { ScheduleKind } from "@/types/triggers";

/** A template's suggested cadence - one of the two disjoint schedule shapes. */
export interface ScheduleTemplateCadence {
  schedule_kind: ScheduleKind;
  interval_seconds?: number | null;
  cron_expression?: string | null;
}

export interface ScheduleTemplate {
  key: string;
  label: string;
  description: string;
  prompt: string;
  suggested_cadence: ScheduleTemplateCadence;
}

export interface ScheduleTemplateList {
  items: ScheduleTemplate[];
  total: number;
}
