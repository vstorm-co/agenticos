"use client";

import { useLocale, useTranslations } from "next-intl";
import { Badge, Button } from "@/components/ui";
import { useCodingAccountUsage } from "@/hooks/use-coding-account-usage";
import type {
  CodingAccount,
  ProviderUsageStatus,
  ProviderUsageWindow,
} from "@/lib/coding-accounts-api";

const REASONS = {
  provider_contract_unverified: "unverified",
  telemetry_unavailable: "notReported",
  missing_observation_window: "unverified",
  invalid_observation_timezone: "unverified",
  invalid_validity_timezone: "unverified",
  clock_skew: "unverified",
  stale_observation: "stale",
  usage_windows_unavailable: "windowsUnknown",
  provider_reported_rate_limit: "rateLimited",
  provider_authentication_required: "signInRequired",
  provider_capacity_unavailable: "capacityUnavailable",
  provider_busy: "busy",
  provider_identity_mismatch: "identityMismatch",
  provider_readiness_unavailable: "readinessUnknown",
  provider_reported_quota_exhausted: "quotaExhausted",
  runtime_version_unsupported: "runtimeUnsupported",
  model_catalog_unverified: "modelsUnknown",
  telemetry_unsupported: "unsupported",
  probe_timeout: "probeTimeout",
} as const;

function timestamp(value: string, locale: string): string {
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "long" });
}

function ReportTimes({
  observedAt,
  validUntil,
}: {
  observedAt: string | null;
  validUntil: string | null;
}) {
  const t = useTranslations("codingAccounts.usage");
  const locale = useLocale();
  return (
    <p className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {observedAt && Number.isFinite(Date.parse(observedAt)) && (
        <time dateTime={observedAt} title={observedAt}>
          {t("observed", { time: timestamp(observedAt, locale) })}
        </time>
      )}
      {validUntil && Number.isFinite(Date.parse(validUntil)) && (
        <time dateTime={validUntil} title={validUntil}>
          {t("validUntil", { time: timestamp(validUntil, locale) })}
        </time>
      )}
    </p>
  );
}

function UsageWindow({ window }: { window: ProviderUsageWindow }) {
  const t = useTranslations("codingAccounts.usage");
  const locale = useLocale();
  const minutes = window.window_duration_minutes;
  const name =
    minutes && minutes > 0
      ? minutes % 1440 === 0
        ? t("windowDays", { count: minutes / 1440 })
        : minutes % 60 === 0
          ? t("windowHours", { count: minutes / 60 })
          : t("windowMinutes", { count: minutes })
      : window.name;
  const amount = (value: number | null) =>
    value === null ? t("unknown") : value.toLocaleString(locale);
  return (
    <li className="bg-background/70 min-w-0 space-y-1 rounded-lg border p-3">
      <p className="text-xs font-medium">{name}</p>
      <p className="text-sm tabular-nums">
        {window.used === null && window.limit === null
          ? t("windowsUnknown")
          : t("windowUsage", {
              used: amount(window.used),
              limit: amount(window.limit),
              unit: window.unit === "percent" ? "%" : (window.unit ?? ""),
            })}
      </p>
      <p className="text-muted-foreground text-xs break-words">
        {window.resets_at && Number.isFinite(Date.parse(window.resets_at)) ? (
          <time dateTime={window.resets_at} title={window.resets_at}>
            {t("resetsAt", { time: timestamp(window.resets_at, locale) })}
          </time>
        ) : (
          t("resetUnknown")
        )}
      </p>
    </li>
  );
}

/** Readiness and reported usage remain separate: a percentage never decides availability. */
export function CodingAccountUsage({ account }: { account: CodingAccount }) {
  const t = useTranslations("codingAccounts.usage");
  const actions = useCodingAccountUsage(account);
  const raw = actions.report?.usage;
  const expires = raw?.valid_until ? Date.parse(raw.valid_until) : Number.NaN;
  const stale = Number.isFinite(expires) && expires <= actions.now;
  const fresh =
    account.enabled &&
    actions.supported &&
    raw?.observed_at !== null &&
    Number.isFinite(Date.parse(raw?.observed_at ?? "")) &&
    expires > actions.now &&
    raw?.source !== "unavailable";
  const status: ProviderUsageStatus = !account.enabled
    ? "disabled"
    : fresh && raw
      ? raw.status
      : "unknown";
  const reason = !account.enabled
    ? "disabled"
    : !actions.supported
      ? "unsupported"
      : stale
        ? "stale"
        : raw?.reason_code && Object.hasOwn(REASONS, raw.reason_code)
          ? REASONS[raw.reason_code as keyof typeof REASONS]
          : fresh
            ? null
            : "notReported";
  const catalog = actions.report?.model_catalog;
  const modelsFresh = Boolean(
    account.enabled &&
    actions.supported &&
    catalog?.status === "advertised" &&
    catalog.observed_at &&
    catalog.valid_until &&
    Date.parse(catalog.valid_until) > actions.now,
  );
  const windows = fresh ? (raw?.windows ?? []) : [];
  return (
    <section
      aria-label={t("title", { label: account.label })}
      className="bg-muted/30 w-full min-w-0 basis-full space-y-3 rounded-xl border p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium">{t("heading")}</p>
          <Badge variant="outline">{t("status", { status: t(`statuses.${status}`) })}</Badge>
          <p className="text-muted-foreground text-xs">
            {t("source", { source: t(`sources.${fresh && raw ? raw.source : "unavailable"}`) })}
          </p>
        </div>
        {account.enabled && actions.supported && (
          <Button
            size="sm"
            variant="outline"
            disabled={!actions.ready || actions.changed || actions.refreshing || actions.pending}
            onClick={actions.requestRefresh}
          >
            {t("refresh")}
          </Button>
        )}
      </div>
      {actions.changed ? (
        <p role="status" className="text-muted-foreground text-xs">
          {t("changed")}
        </p>
      ) : reason ? (
        <p className="text-muted-foreground text-xs leading-relaxed">{t(reason)}</p>
      ) : null}
      {account.enabled && actions.supported && raw && (
        <ReportTimes observedAt={raw.observed_at} validUntil={raw.valid_until} />
      )}
      {windows.length > 0 && (
        <ul className="grid gap-2 sm:grid-cols-2">
          {windows.map((window, index) => (
            <UsageWindow key={`${window.name}:${index}`} window={window} />
          ))}
        </ul>
      )}
      {fresh && windows.length === 0 && reason !== "windowsUnknown" && (
        <p className="text-muted-foreground text-xs">{t("windowsUnknown")}</p>
      )}
      <div className="space-y-2 border-t pt-3">
        <p className="text-xs font-medium">{t("models")}</p>
        {modelsFresh && catalog ? (
          <>
            <ul className="flex flex-wrap gap-1.5">
              {catalog.model_ids.map((id) => (
                <li key={id} className="max-w-full">
                  <Badge variant="outline" className="max-w-full break-all whitespace-normal">
                    {id}
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground text-xs">
              {t("source", { source: t(`sources.${catalog.source}`) })}
            </p>
            <ReportTimes observedAt={catalog.observed_at} validUntil={catalog.valid_until} />
            <p className="text-muted-foreground text-xs leading-relaxed">{t("modelsHint")}</p>
          </>
        ) : (
          <p className="text-muted-foreground text-xs">{t("modelsUnknown")}</p>
        )}
      </div>
      {(actions.refreshing || actions.pending) && (
        <p role="status" className="text-muted-foreground text-xs">
          {t(actions.refreshing ? "requesting" : actions.pollExpired ? "pendingLong" : "pending")}
        </p>
      )}
      {actions.error && !actions.changed && (
        <p role="alert" className="text-destructive text-xs">
          {t("readFailed")}
        </p>
      )}
      {(actions.pollExpired || actions.error) &&
        actions.ready &&
        account.enabled &&
        actions.supported && (
          <Button
            size="sm"
            variant="outline"
            disabled={actions.checking}
            onClick={() => void actions.check()}
          >
            {t(actions.checking ? "checking" : "check")}
          </Button>
        )}
    </section>
  );
}
