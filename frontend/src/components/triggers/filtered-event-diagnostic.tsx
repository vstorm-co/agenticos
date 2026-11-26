"use client";

import { useLocale, useTranslations } from "next-intl";
import { ErrorState, LoadingState } from "@/components/states";
import { useTriggerFilteredEvent } from "@/hooks/use-triggers";
import { useAuthStore } from "@/stores";
import type { Trigger } from "@/types/triggers";

export function FilteredEventDiagnostic({ trigger }: { trigger: Trigger }) {
  const me = useAuthStore((state) => state.user?.id);
  const enabled = Boolean(
    me && me === trigger.created_by_user_id && trigger.event_source === "github",
  );
  const query = useTriggerFilteredEvent(trigger, enabled);
  const t = useTranslations("triggers");
  const portals = useTranslations("portals");
  const locale = useLocale();
  if (!enabled) return null;
  if (query.isLoading) return <LoadingState variant="pending" className="m-5" />;
  if (query.error)
    return (
      <ErrorState
        title={t("filteredEventError")}
        className="m-5"
        cta={{ label: t("attemptsRetry"), onClick: () => void query.refetch() }}
      />
    );
  const event = query.data?.last_event;
  return (
    <section className="border-border border-b px-5 py-3">
      <h3 className="text-sm font-medium">{t("filteredEventTitle")}</h3>
      <p className="text-muted-foreground mt-1 text-xs">{t("filteredEventHint")}</p>
      {event ? (
        <div className="mt-2 space-y-1 text-sm">
          <time dateTime={event.received_at}>
            {new Date(event.received_at).toLocaleString(locale, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </time>
          <p>{t(`filteredEventReason.${event.reason}`)}</p>
          <p className="text-muted-foreground text-xs">
            {t("filteredEventPolicy", { policy: portals(`githubAuthors.${event.authors}`) })}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm">{t("filteredEventEmpty")}</p>
      )}
    </section>
  );
}
