"use client";

import { useTranslations } from "next-intl";

import { StatusList, type StatusRow, type StatusTone } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";
import { usePermissions, useRuns } from "@/hooks";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { cadenceText } from "@/lib/trigger-format";
import { Perm } from "@/types/permissions";
import type { Translate } from "@/lib/agent-step-captions";
import type { AgentRun } from "@/types/runs";
import type { Trigger } from "@/types/triggers";

/** How many routines the card lists before it defers to the page. */
const SHOWN = 6;

/**
 * What runs with nobody at the keyboard, and how the last one went.
 *
 * The seam #594 asks for: triggers and the arrangeable dashboard were built on
 * branches that could not see each other, so the one addable card that would
 * surface `/routines` did not exist and an organization's unattended work was
 * visible only to whoever went looking for it.
 *
 * **Two reads, joined here, and no new endpoint.** The org-wide `GET /triggers`
 * carries the definitions - cadence, whether it is paused, when it fires next,
 * and the id of the run its last fire started. What that run *did* is the run's
 * own row, so the recent unattended runs are read once and joined on
 * `last_run_id`. A per-row fetch would be one request per card row.
 *
 * The runs half is conditional on `runs:view`, which the triggers half does not
 * need (`GET /triggers` asks for `agents:view`). So a reader who may see agents
 * but not runs gets the routines and their next fire, rather than a card that
 * 403s on a permission it never needed - and the widget's own gate is the
 * permission its *primary* data demands.
 *
 * A schedule and an event trigger are told apart by `trigger_type`, never by the
 * run's surface: an event-fired run is stamped `SCHEDULE` too, so a
 * surface-based split would put both families in one bucket.
 */
export function RoutinesWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.routines");
  // The cadence sentence belongs to the triggers namespace, where the trigger
  // row and the chat's own summary read it from - one wording for "every 15
  // minutes" across the product rather than a second copy under this card.
  const tt = useTranslations("triggers");
  const { can } = usePermissions();
  const mayReadRuns = can(Perm.runsView);
  const { triggers, isLoading, isError, refetch } = useOrgTriggers();
  const { runs } = useRuns(undefined, { surface: "schedule", enabled: mayReadRuns });

  if (isLoading) {
    return (
      <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
        <WidgetSkeleton />
      </WidgetFrame>
    );
  }

  const lastRun = new Map(runs.map((run) => [run.id, run]));
  // Paused last, then the ones that fire soonest: a card of six rows should hold
  // what is about to happen, and a paused routine is not about to happen. An
  // event trigger has no next fire at all, so it sorts after the schedules and
  // before the paused - it is live, it is simply not on a clock.
  const rows = [...triggers]
    .sort((left, right) => rank(left) - rank(right) || due(left) - due(right))
    .slice(0, SHOWN)
    .map((trigger) => row(trigger, lastRun.get(trigger.last_run_id ?? ""), t, tt));

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isError ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <StatusList rows={rows} />
      )}
    </WidgetFrame>
  );
}

/** Paused after live, and an event trigger between the two - see the sort above. */
function rank(trigger: Trigger): number {
  if (!trigger.is_active) return 2;
  return trigger.next_fire_at === null ? 1 : 0;
}

function due(trigger: Trigger): number {
  return trigger.next_fire_at === null ? 0 : new Date(trigger.next_fire_at).getTime();
}

/**
 * One routine as a status row.
 *
 * The pill is the *outcome*, because that is the question a glance asks: a
 * routine that has been failing every hour for a day looks exactly like a
 * healthy one if the card only says when it next fires. What it cost goes in the
 * subtitle beside the cadence, where it is legible without competing.
 */
function row(trigger: Trigger, run: AgentRun | undefined, t: Translate, tt: Translate): StatusRow {
  const [pill, tone] = outcome(trigger, run, t);
  return {
    label: trigger.name ?? trigger.agent_name ?? t("unnamed"),
    sub: [cadenceText(trigger, tt), run ? t("cost", { cost: run.cost_usd }) : null]
      .filter((part) => part !== null)
      .join(" · "),
    pill,
    tone,
  };
}

function outcome(trigger: Trigger, run: AgentRun | undefined, t: Translate): [string, StatusTone] {
  if (!trigger.is_active) return [t("paused"), "neutral"];
  if (trigger.last_fired_at === null) return [t("neverRun"), "neutral"];
  // Fired, but the run it started is not in the page of recent ones - it is older
  // than the page reaches, or this reader may not read runs at all. Saying
  // "succeeded" would be a guess and saying "failed" a worse one.
  if (run === undefined) return [t("fired"), "neutral"];
  if (run.status === "failed" || run.status === "budget_exceeded")
    return [t(`status.${run.status}`), "err"];
  if (run.down_rated) return [t("ratedDown"), "warn"];
  if (run.status === "completed") return [t("succeeded"), "ok"];
  return [t(`status.${run.status}`), "neutral"];
}
