"use client";

import Link from "next/link";
import { AlertTriangle, ChevronDown, Clock, RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import type { BridgeStatus, DataBridge } from "@/components/artifacts/artifact-frame";
import type { LiveHealth } from "@/components/artifacts/live-badge";
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
 * The last read was of a version no longer current: the console is moving to
 * the newer one, so its unavailable sources say nothing about the page.
 */
function superseded(status: BridgeStatus): boolean {
  return status.error === null && status.data?.current === false;
}

/**
 * Every source waits for the owner's consent, as the address said when it was minted
 * for a page served with its data: known before any read, and for any viewer. Once
 * a read answers, it is the read that says.
 */
function waiting(status: BridgeStatus): boolean {
  const { served } = status;
  return (
    status.data === undefined && served !== null && served.bindings > 0 && served.awaitingConsent
  );
}

/**
 * Whether polling this page can bring anything: not after a refusal, and not
 * when the last read answered with no source available.
 *
 * Read from `status` alone, never `reason`, which only an editor is sent - a
 * reader who lost the table has to stop too. Any other failure - a 429 after
 * its retries, a 5xx - is not an answer about the page, so it keeps polling;
 * nor is a read of a version since replaced, whose sources all answer
 * unavailable while the console moves to the newer one.
 */
function stopsAutoRefresh(status: BridgeStatus): boolean {
  if (refused(status)) return true;
  if (status.error !== null || superseded(status)) return false;
  if (waiting(status)) return true;
  const bindings = Object.values(status.data?.bindings ?? {});
  return bindings.length > 0 && bindings.every((binding) => binding.status === "unavailable");
}

/**
 * What the badge beside the title shows, by the same reading `LiveDataNotice`
 * makes: some sources unavailable is `partial`, all answering is `flowing`. A
 * refusal, or no source available, is `null` - no badge, since nothing on the
 * page is live for this viewer, and the notice says why. A read still to come,
 * a transient failure or a read of a replaced version says nothing about the
 * sources.
 */
export function liveHealth(status: BridgeStatus): LiveHealth | null {
  if (refused(status)) return null;
  if (status.error !== null || superseded(status)) return "steady";
  if (waiting(status)) return null;
  const bindings = Object.values(status.data?.bindings ?? {});
  if (bindings.length === 0) return "steady";
  const unavailable = bindings.filter((binding) => binding.status === "unavailable").length;
  if (unavailable === bindings.length) return null;
  return unavailable > 0 ? "partial" : "flowing";
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
  /** The `data-tour` anchor, for a notice the onboarding walk points at. */
  tour?: string;
}

/**
 * The one line under the viewer's strip, drawn only when something about the
 * page needs attention. Themed through the console's tokens, so it follows the
 * console's theme switch rather than the operating system's.
 */
export function ViewerNotice({ tone, icon: Icon, children, tour }: ViewerNoticeProps) {
  return (
    <div
      role="status"
      data-tour={tour}
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
 *
 * Data waiting for the owner's consent is said once, for the whole page, and only
 * to its audience: a caller served the latest version has the consent strip
 * (`ConsentNotice`) saying it, with what to do.
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
  if (status.error !== null || superseded(status)) return null;
  const bindings = Object.entries(status.data?.bindings ?? {});
  const unavailable = bindings.filter(([, binding]) => binding.status === "unavailable");
  const awaiting =
    waiting(status) ||
    (unavailable.length > 0 &&
      unavailable.every(([, binding]) => binding.reason === "awaiting_consent"));
  if (unavailable.length === 0 && !awaiting) return null;
  if (awaiting) {
    if (artifact.consent !== null) return null;
    return (
      <ViewerNotice tone="info" icon={Clock}>
        {t("consent.awaitingForYou")}
      </ViewerNotice>
    );
  }
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
                  changed: binding.changed ?? "",
                  b: (chunks) => <span className="font-medium">{chunks}</span>,
                })}
              </span>
              {bound !== undefined && (
                <Button asChild size="sm" variant="outline" className="h-6 px-2">
                  {bound.kind === "workflow_log" ? (
                    <Link href={ROUTES.WORKFLOW_DETAIL(bound.workflow_id)}>
                      {t("openWorkflow")}
                    </Link>
                  ) : (
                    <Link href={ROUTES.TABLE_DETAIL(bound.table_id)}>{t("openTable")}</Link>
                  )}
                </Button>
              )}
            </span>
          );
        })}
    </ViewerNotice>
  );
}
