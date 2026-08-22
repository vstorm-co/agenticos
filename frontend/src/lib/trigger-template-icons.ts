/**
 * Which mark a trigger template's card draws, keyed on the template's own key.
 *
 * Here rather than in the API payload, and that is the whole decision: which glyph
 * illustrates a card is a presentation choice, and the catalog
 * (`backend/app/core/catalog/trigger_templates.json`) has no business holding one -
 * the same reason `tool-catalog.ts` keeps icons on this side of the wire.
 *
 * Four grey rectangles of two text lines each is a grid nobody scans, which is what
 * `Start from a template` was before this (#1069). A schedule template gets a lucide
 * glyph for what it *does*; an event template's brand mark comes from
 * `event-source-mark.tsx` instead, because a card for a GitHub issue should carry
 * GitHub's own mark rather than a generic one.
 *
 * A key with no row here falls back to `Sparkles`, so a template added to the
 * catalog renders correctly the day it lands and gains its own glyph later.
 */

import {
  Bell,
  CalendarDays,
  ClipboardList,
  FileText,
  GitPullRequest,
  ListChecks,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  pr_digest_weekday_mornings: GitPullRequest,
  triage_new_issues_daily: ListChecks,
  standup_prep_weekdays: Users,
  weekly_team_summary: FileText,
  monthly_report: CalendarDays,
  hourly_monitoring: Bell,
  github_triage_new_issue: ListChecks,
  email_draft_reply: FileText,
  email_action_items: ClipboardList,
  webhook_act_on_delivery: Sparkles,
};

/** The glyph for a template key, or the fallback for one with no row. */
export function templateIcon(key: string): LucideIcon {
  return ICONS[key] ?? Sparkles;
}
