"use client";

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useTranscriptionUsage } from "@/hooks/use-transcription-usage";
import type { TranscriptionUsageGroup } from "@/lib/dictation-api";
import { Perm } from "@/types/permissions";

/** The window the line reports on; the summary route's own default. */
const DAYS = 30;

/**
 * One line on the Voice card saying how much the organization transcribed -
 * "Last 30 days: 42 min · 118 recordings (30 without a length)" - and, on
 * request, the same by agent and by channel bot (#1797).
 *
 * Only for `runs:view`, like the spend figures: the breakdown names agents and
 * bots, and the route refuses anyone else, so nothing is asked for them. Hidden
 * while loading, on a failure and when nothing was transcribed - a line saying
 * "0 recordings" beside a provider nobody has used yet is noise.
 *
 * The minutes are an under-count whenever a recording's length went
 * unreported, so the line says how many did rather than letting them read as
 * silence.
 */
export function OrgVoiceUsage() {
  const { can } = usePermissions();
  const usage = useTranscriptionUsage(DAYS, { enabled: can(Perm.runsView) });
  const t = useTranslations("teams");
  const duration = useDuration();
  const [open, setOpen] = useState(false);
  const breakdownId = useId();
  if (usage === null || usage.count === 0) return null;
  return (
    <section aria-label={t("voice.usage.label")} className="mb-4 text-sm">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="text-muted-foreground">
          {t("voice.usage.summary", {
            days: usage.days,
            duration: duration(usage.seconds),
            count: usage.count,
          })}
          {usage.count_unknown_length > 0 && (
            <> {t("voice.usage.unknown", { count: usage.count_unknown_length })}</>
          )}
        </p>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          aria-expanded={open}
          aria-controls={breakdownId}
          onClick={() => setOpen((shown) => !shown)}
        >
          {open ? t("voice.usage.hide") : t("voice.usage.show")}
          <ChevronDown className={open ? "h-3.5 w-3.5 rotate-180" : "h-3.5 w-3.5"} aria-hidden />
        </Button>
      </div>
      {open && (
        <div id={breakdownId} className="mt-2 grid gap-3 sm:grid-cols-2">
          <Breakdown
            title={t("voice.usage.byAgent")}
            groups={usage.by_agent.map((group) => ({ ...group, id: group.agent_id }))}
          />
          <Breakdown
            title={t("voice.usage.byChannel")}
            groups={usage.by_channel.map((group) => ({ ...group, id: group.channel_bot_id }))}
          />
          {usage.count_unknown_length > 0 && (
            <p className="text-muted-foreground text-xs sm:col-span-2">
              {t("voice.usage.unknownNote")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** One breakdown as a plain list; nothing at all when it has no rows. */
function Breakdown({
  title,
  groups,
}: {
  title: string;
  groups: (TranscriptionUsageGroup & { id: string })[];
}) {
  const t = useTranslations("teams");
  const duration = useDuration();
  if (groups.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold">{title}</h4>
      <ul className="mt-1 space-y-0.5 text-xs">
        {groups.map((group) => (
          <li key={group.id} className="flex justify-between gap-3">
            <span className="truncate">{group.name}</span>
            <span className="text-muted-foreground shrink-0 tabular-nums">
              {t("voice.usage.rowStats", { duration: duration(group.seconds), count: group.count })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Seconds as whole minutes, and "under 1 min" for a few seconds rather than "0 min". */
function useDuration(): (seconds: number) => string {
  const t = useTranslations("teams");
  return (seconds) => {
    const minutes = Math.round(seconds / 60);
    return seconds > 0 && minutes === 0
      ? t("voice.usage.underMinute")
      : t("voice.usage.minutes", { minutes });
  };
}
