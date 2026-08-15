"use client";

import type { LucideIcon } from "lucide-react";
import { Activity, Boxes, Cpu, Database, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { useSystemHealth } from "@/hooks";
import type { CheckStatus, SystemCheck } from "@/types/admin";
import { resolveStyle } from "@/lib/dashboard/registry";
import { cn } from "@/lib/utils";
import { StatusList, type StatusTone } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The four probes the backend runs, each with the icon that says which
 * subsystem it is (`app/services/health.py`). A key this table does not know is
 * a probe added since - it takes the generic mark and its own name, rather than
 * being dropped from a card whose whole job is to be complete.
 */
const ICON: Record<string, LucideIcon> = {
  database: Database,
  redis: Zap,
  vector_store: Boxes,
  model_access: Cpu,
};

/** The same four, as copy. Anything else prints its key, humanised. */
const NAMED = new Set(Object.keys(ICON));

const TILE: Record<CheckStatus, string> = {
  healthy: "bg-success/12 text-success",
  unhealthy: "bg-destructive/12 text-destructive",
  unconfigured: "bg-muted text-muted-foreground",
  not_checked: "bg-muted text-muted-foreground",
};

/** The list style's dot, for the four statuses this endpoint answers with. */
const TONE: Record<CheckStatus, StatusTone> = {
  healthy: "ok",
  unhealthy: "err",
  unconfigured: "neutral",
  not_checked: "neutral",
};

const WORD: Record<CheckStatus, string> = {
  healthy: "text-success",
  unhealthy: "text-destructive",
  unconfigured: "text-muted-foreground",
  not_checked: "text-muted-foreground",
};

/**
 * The deployment's service probes, as the admin system page reports them.
 *
 * A row of tiles rather than a list of rows: four services with one word each
 * spent a whole card's height on four lines of mostly whitespace, and the
 * question the card answers - is anything down - is one a reader should be able
 * to take in without reading. Colour is never carrying it alone: every tile
 * prints its status under the icon, and a probe that is failing keeps its detail
 * on the hover, which is where the list used to print it.
 */
export function HealthWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.health");
  const { health, isLoading, error, refetch } = useSystemHealth();
  const style = resolveStyle("health", options?.style);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !health || health.checks.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : style === "list" ? (
        // The rows this card used to be, kept as a choice rather than deleted:
        // a deployment that grows a dozen probes wants names down a column, and
        // a failing probe's detail reads better on its own line than on a hover.
        <StatusList
          rows={health.checks.map((check) => ({
            label: NAMED.has(check.key) ? t(`services.${check.key}`) : check.key.replace(/_/g, " "),
            sub: check.status === "healthy" ? undefined : check.detail,
            pill: t(`status.${check.status}`),
            tone: TONE[check.status],
          }))}
        />
      ) : (
        <ul className="grid flex-1 auto-rows-min grid-cols-4 content-center gap-x-2 gap-y-4">
          {health.checks.map((check) => (
            <ServiceTile key={check.key} check={check} />
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}

function ServiceTile({ check }: { check: SystemCheck }) {
  const t = useTranslations("dashboard.widgets.health");
  const Icon = ICON[check.key] ?? Activity;
  const name = NAMED.has(check.key) ? t(`services.${check.key}`) : check.key.replace(/_/g, " ");
  const word = t(`status.${check.status}`);

  return (
    <li className="flex min-w-0 flex-col items-center gap-1.5 text-center">
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn("grid size-9 shrink-0 place-items-center rounded-xl", TILE[check.status])}
          >
            <Icon className="size-4.5" aria-hidden />
          </span>
        </TooltipTrigger>
        {/* The detail is the failing probe's own message - what a list row used
            to print under the name, and the only thing on this card that says
            *why* something is down. */}
        <TooltipContent side="top" className="max-w-64">
          {check.detail ? `${name} — ${check.detail}` : `${name} — ${word}`}
        </TooltipContent>
      </Tooltip>
      <span className="text-foreground w-full text-xs leading-tight break-words">{name}</span>
      <span className={cn("text-[11px] leading-none", WORD[check.status])}>{word}</span>
      {/* The hover is a pointer's affordance and nothing else's: the tile is not
          a control, so it is deliberately not a tab stop, and a reader who
          cannot hover would otherwise never reach the one sentence saying why a
          probe is down. */}
      {check.detail ? <span className="sr-only">{check.detail}</span> : null}
    </li>
  );
}
