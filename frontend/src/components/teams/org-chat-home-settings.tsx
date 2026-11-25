"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { MessageSquare, BellRing, Coins, PanelLeft, Megaphone } from "lucide-react";
import { toast } from "sonner";
import { usePermissions } from "@/hooks/use-permissions";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import { useOrgStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ChatHomeOverrides,
  OnboardingReminderOverrides,
  ChatCostVisibility,
  ConsoleRoleDefaults,
  ConsoleNotices,
} from "@/lib/console-experience-api";
import { Perm } from "@/types/permissions";
import type { Organization, OrgRole } from "@/types/organization";
import { ErrorState } from "@/components/states";
import { ServiceCard } from "@/components/settings/service-card";
import { OnboardingReminderControls } from "@/components/settings/onboarding-reminder-controls";
import { OrganizationChatCostControl } from "@/components/settings/chat-cost-controls";
import { OrganizationConsoleNavigation } from "./org-console-navigation";
import { ConsoleNoticeControls } from "@/components/settings/console-notice-controls";
import { ChatHomeControls } from "@/components/settings/chat-home-controls";

type OrganizationExperience = Pick<
  Organization,
  | "id"
  | "chat_home_defaults"
  | "onboarding_reminders"
  | "chat_cost_visibility"
  | "console_role_defaults"
  | "console_notices"
>;

export function OrgChatHomeSettings({ org }: { org: OrganizationExperience }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { can } = usePermissions();
  if (activeOrgId !== org.id || !can(Perm.orgSettings)) return null;
  return <OrganizationChatHome org={org} />;
}
function OrganizationChatHome({ org }: { org: OrganizationExperience }) {
  const t = useTranslations("consoleExperience");
  const errors = useTranslations("errors");
  const client = useQueryClient();
  const experience = useConsoleExperience();
  const { data } = experience;
  const save = useMutation({
    mutationFn: (changes: {
      chat_home_defaults?: ChatHomeOverrides;
      chat_cost_visibility?: ChatCostVisibility;
      console_role_defaults?: Partial<Record<OrgRole, ConsoleRoleDefaults | null>>;
      console_notices?: ConsoleNotices;
      onboarding_reminders?: OnboardingReminderOverrides;
    }) => {
      if (useOrgStore.getState().activeOrgId !== org.id) throw new Error(errors("sessionExpired"));
      return apiClient.patch<Organization>(`/orgs/${org.id}`, changes, {
        headers: { "X-Organization-Id": org.id },
      });
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.organizations.list() }),
        client.invalidateQueries({ queryKey: qk.consoleExperience.all() }),
        client.invalidateQueries({ queryKey: qk.mcpServers.catalog() }),
        client.invalidateQueries({ queryKey: qk.mcpServers.lists() }),
        client.invalidateQueries({ queryKey: qk.mcpServers.entries() }),
        client.invalidateQueries({ queryKey: qk.skills.gallery() }),
      ]);
    },
    onError: (error) => toast.error(getErrorMessage(error, errors)),
  });
  return (
    <>
      <ServiceCard
        icon={PanelLeft}
        action={null}
        title={t("presentation.organizationTitle")}
        description={t("presentation.organizationHint")}
        collapsible
        toggleTour="organization-console-navigation-expand"
      >
        {data?.presentation && (
          <OrganizationConsoleNavigation
            key={org.id}
            defaults={org.console_role_defaults}
            presentation={data.presentation}
            disabled={save.isPending}
            onSave={(role, changes, onSaved) =>
              save.mutate({ console_role_defaults: { [role]: changes } }, { onSuccess: onSaved })
            }
          />
        )}
      </ServiceCard>
      <ServiceCard
        icon={Megaphone}
        action={null}
        title={t("presentation.noticesTitle")}
        description={t("presentation.noticesHint")}
      >
        <div data-tour="organization-console-notices">
          <ConsoleNoticeControls
            mode="availability"
            value={org.console_notices}
            ceiling={data?.presentation?.notices_available}
            disabled={save.isPending || !data}
            onChange={(console_notices) => save.mutate({ console_notices })}
          />
        </div>
      </ServiceCard>
      <ServiceCard
        icon={MessageSquare}
        action={null}
        title={t("title")}
        description={t("organizationHint")}
      >
        {experience.error && (
          <ErrorState cta={{ label: t("retry"), onClick: () => void experience.refetch() }} />
        )}
        <ChatHomeControls
          mode="inheritance"
          value={org.chat_home_defaults}
          availability={data?.availability}
          disabled={save.isPending || !data}
          onChange={(field, value) => save.mutate({ chat_home_defaults: { [field]: value } })}
        />
      </ServiceCard>
      <ServiceCard
        icon={Coins}
        action={null}
        title={t("costs.title")}
        description={t("costs.organizationHint")}
      >
        <OrganizationChatCostControl
          value={org.chat_cost_visibility ?? "everyone"}
          disabled={save.isPending || !data || data.costs?.availability === false}
          onChange={(chat_cost_visibility) => save.mutate({ chat_cost_visibility })}
        />
        {data?.costs?.availability === false && (
          <p className="text-muted-foreground mt-2 text-xs">{t("unavailable")}</p>
        )}
      </ServiceCard>
      <ServiceCard
        icon={BellRing}
        action={null}
        title={t("remindersTitle")}
        description={t("remindersOrganizationHint")}
      >
        <OnboardingReminderControls
          value={org.onboarding_reminders}
          available={data?.reminders.availability}
          disabled={save.isPending || !data}
          onChange={(onboarding_reminders) => save.mutate({ onboarding_reminders })}
        />
      </ServiceCard>
    </>
  );
}
