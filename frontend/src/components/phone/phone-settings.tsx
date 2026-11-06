"use client";
import { useState } from "react";
import { useOrgStore } from "@/stores";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { usePhoneCalls, usePhoneSettings } from "@/hooks/use-phone";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { PhoneContactForm } from "./phone-contact";
import { PhoneRouting } from "./phone-routing";
import { PhoneDialer } from "./phone-dialer";
import { PhoneReceiptCard } from "./phone-call-card";
export function PhoneSettings({ administration = false }: { administration?: boolean }) {
  const org = useOrgStore((state) => state.activeOrgId);
  return <PhoneSettingsContent key={org ?? "current"} administration={administration} />;
}
function PhoneSettingsContent({ administration }: { administration: boolean }) {
  const t = useTranslations("phone");
  const { can } = usePermissions();
  const query = usePhoneSettings();
  const calls = usePhoneCalls();
  const [attempt, setAttempt] = useState(0);
  if (query.isLoading) return <p className="text-muted-foreground text-sm">{t("loading")}</p>;
  if (query.error || !query.data)
    return <ErrorState cta={{ label: t("refresh"), onClick: () => void query.refetch() }} />;
  const data = query.data;
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <div className="space-y-6">
        {administration && can(Perm.channelsManage) ? (
          <PhoneRouting
            settings={data}
            pending={query.configure.isPending}
            onSave={(botId, config) => query.configure.mutate({ botId, data: config })}
          />
        ) : null}
        {!administration ? (
          <PhoneContactForm
            key={data.contact?.id ?? "new"}
            settings={data}
            pending={query.saveContact.isPending}
            onSave={(contact) => query.saveContact.mutate(contact)}
          />
        ) : null}
        {!administration && data.call_endpoints.length ? (
          <PhoneDialer
            key={attempt}
            endpoints={data.call_endpoints}
            pending={query.call.isPending}
            onCall={(call) =>
              query.call.mutate(call, { onSuccess: () => setAttempt((value) => value + 1) })
            }
          />
        ) : null}
        <h3 className="text-sm font-medium">{t("recentCalls")}</h3>
        {calls.error ? (
          <ErrorState cta={{ label: t("refresh"), onClick: () => void calls.refetch() }} />
        ) : calls.data?.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {calls.data.map((call) => (
              <PhoneReceiptCard key={call.id} call={call} />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            {calls.isLoading ? t("loading") : t("noCalls")}
          </p>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            void query.refetch();
            void calls.refetch();
          }}
        >
          {t("refresh")}
        </Button>
      </div>
    </SectionCard>
  );
}
