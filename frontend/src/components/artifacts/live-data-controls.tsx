"use client";

import Link from "next/link";
import { AlertTriangle, ChevronDown, RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import type { BridgeStatus, DataBridge } from "@/components/artifacts/artifact-frame";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { AUTO_REFRESH_MINUTES, useAutoRefresh } from "@/hooks/use-auto-refresh";
import { ApiError } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { ArtifactDetail } from "@/types/artifact";

/** The data answered 403 or 404: it is gone for this viewer, not busy. */
function refused(status: BridgeStatus): boolean {
  return status.error instanceof ApiError && [403, 404].includes(status.error.status);
}

function busy(status: BridgeStatus): boolean {
  return status.error instanceof ApiError && status.error.status === 429;
}

/**
 * Whether polling this page can bring anything: not after a refusal, and not
 * when the last read answered with no source available.
 *
 * Read from `status` alone, never `reason`, which only an editor is sent - a
 * reader who lost the table has to stop too. Any other failure - a 429 after
 * its retries, a 5xx - is not an answer about the page, so it keeps polling.
 */
function stopsAutoRefresh(status: BridgeStatus): boolean {
  if (refused(status)) return true;
  if (status.error !== null) return false;
  const bindings = Object.values(status.data?.bindings ?? {});
  return bindings.length > 0 && bindings.every((binding) => binding.status === "unavailable");
}

/** When the last read answered, as the strip says it. */
function useUpdatedAt(status: BridgeStatus): string | null {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  const readAt = status.data?.read_at;
  if (readAt === undefined) return null;
  return t("refreshedAt", { time: format.dateTime(new Date(readAt), { timeStyle: "short" }) });
}

interface LiveRefreshButtonProps {
  artifactId: string;
  bridge: DataBridge;
}

/**
 * Refresh, and beside it the auto-refresh menu: one split button in the strip.
 *
 * When it was last read sits in the button's title and the menu's header rather
 * than in the strip, which says something only when it needs attention
 * (`LiveDataNotice`).
 */
export function LiveRefreshButton({ artifactId, bridge }: LiveRefreshButtonProps) {
  const t = useTranslations("artifacts");
  const { refresh, status } = bridge;
  const updatedAt = useUpdatedAt(status);
  const { minutes, setMinutes } = useAutoRefresh(
    artifactId,
    () => void refresh(),
    stopsAutoRefresh(status),
  );
  return (
    <div className="flex">
      <Button
        size="sm"
        variant="outline"
        className="rounded-r-none"
        title={updatedAt ?? t("refresh")}
        disabled={status.fetching}
        onClick={() => void refresh()}
      >
        <RefreshCw className={cn("h-3.5 w-3.5", status.fetching && "animate-spin")} aria-hidden />
        <span className="sr-only sm:not-sr-only">{t("refresh")}</span>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            className="rounded-l-none border-l-0 px-1.5"
            aria-label={t("refreshAutomatically")}
          >
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {updatedAt !== null && (
            <>
              <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
                {updatedAt}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuLabel className="text-muted-foreground text-xs font-medium">
            {t("refreshAutomatically")}
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup value={String(minutes)}>
            {AUTO_REFRESH_MINUTES.map((option) => (
              <DropdownMenuRadioItem
                key={option}
                value={String(option)}
                onSelect={() => setMinutes(option)}
              >
                {option === 0 ? t("autoRefreshOff") : t("autoRefreshEvery", { minutes: option })}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

const TONES = {
  warning: "border-warning/30 bg-warning/[0.06] [&>svg]:text-warning",
  info: "border-brand-line bg-brand-subtle [&>svg]:text-brand",
} as const;

interface ViewerNoticeProps {
  tone: keyof typeof TONES;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  children: React.ReactNode;
}

/**
 * The one line under the viewer's strip, drawn only when something about the
 * page needs attention. Themed through the console's tokens, so it follows the
 * console's theme switch rather than the operating system's.
 */
export function ViewerNotice({ tone, icon: Icon, children }: ViewerNoticeProps) {
  return (
    <div
      role="status"
      className={cn(
        "text-foreground flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2 text-sm",
        TONES[tone],
      )}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {children}
    </div>
  );
}

interface LiveDataNoticeProps {
  artifact: ArtifactDetail;
  status: BridgeStatus;
}

/**
 * What is wrong with the page's live data, if anything: refused, busy, or some
 * sources unavailable. A reader is told how many; an editor (`can_edit`, the
 * server's answer) also why, and where to fix each.
 */
export function LiveDataNotice({ artifact, status }: LiveDataNoticeProps) {
  const t = useTranslations("artifacts");
  if (refused(status) || busy(status)) {
    return (
      <ViewerNotice tone="warning" icon={AlertTriangle}>
        {refused(status) ? t("liveDataRefused") : t("liveDataBusy")}
      </ViewerNotice>
    );
  }
  if (status.error !== null) return null;
  const bindings = Object.entries(status.data?.bindings ?? {});
  const unavailable = bindings.filter(([, binding]) => binding.status === "unavailable");
  if (unavailable.length === 0) return null;
  return (
    <ViewerNotice tone="warning" icon={AlertTriangle}>
      <span>
        {t("liveSourcesUnavailable", { count: unavailable.length, total: bindings.length })}
      </span>
      {artifact.can_edit &&
        unavailable.map(([name, binding]) => {
          const bound = artifact.bindings.find((info) => info.name === name);
          return (
            <span key={name} className="inline-flex items-center gap-2">
              <span>
                {t.rich("liveSourceCause", {
                  name,
                  reason: binding.reason ?? "",
                  b: (chunks) => <span className="font-medium">{chunks}</span>,
                })}
              </span>
              {bound !== undefined && (
                <Button asChild size="sm" variant="outline" className="h-6 px-2">
                  <Link
                    href={`${ROUTES.TABLE_DETAIL(bound.table_id)}?viewId=${encodeURIComponent(bound.view_id)}`}
                  >
                    {t("openTable")}
                  </Link>
                </Button>
              )}
            </span>
          );
        })}
    </ViewerNotice>
  );
}
