"use client";

import { useMutation, useQueryClient, type UseMutationOptions } from "@tanstack/react-query";
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

type ExperienceChanges = {
  chat_home_defaults?: ChatHomeOverrides;
  chat_cost_visibility?: ChatCostVisibility;
  console_role_defaults?: Partial<Record<OrgRole, ConsoleRoleDefaults | null>>;
  console_notices?: ConsoleNotices;
  onboarding_reminders?: OnboardingReminderOverrides;
};

type ExperienceSave = {
  ownerOrg: string;
  changes: ExperienceChanges;
  onSaved?: () => void;
};

export function OrgChatHomeSettings({ org }: { org: OrganizationExperience }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { can } = usePermissions();
  if (activeOrgId !== org.id || !can(Perm.orgSettings)) return null;
  return <OrganizationChatHome key={org.id} org={org} />;
}
function OrganizationChatHome({ org }: { org: OrganizationExperience }) {
  const t = useTranslations("consoleExperience");
  const errors = useTranslations("errors");
  const client = useQueryClient();
  const experience = useConsoleExperience();
  const { data } = experience;
  const saveOptions: UseMutationOptions<Organization, Error, ExperienceSave> = {
    scope: { id: `organization-experience-${org.id}` },
    mutationFn: ({ ownerOrg, changes }) => {
      if (useOrgStore.getState().activeOrgId !== ownerOrg)
        throw new Error(errors("sessionExpired"));
      return apiClient.patch<Organization>(`/orgs/${ownerOrg}`, changes, {
        headers: { "X-Organization-Id": ownerOrg },
      });
    },
    onSuccess: async (updated, { ownerOrg, changes, onSaved }) => {
      client.setQueryData<Organization[]>(qk.organizations.list(), (previous) =>
        previous?.map((entry) => (entry.id === ownerOrg ? { ...entry, ...updated } : entry)),
      );
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.organizations.list() }),
        client.invalidateQueries({ queryKey: [...qk.consoleExperience.all(), ownerOrg] }),
        ...(changes.console_role_defaults !== undefined &&
        useOrgStore.getState().activeOrgId === ownerOrg
          ? [
              client.invalidateQueries({ queryKey: qk.mcpServers.catalog() }),
              client.invalidateQueries({ queryKey: qk.mcpServers.lists() }),
              client.invalidateQueries({ queryKey: qk.mcpServers.entries() }),
              client.invalidateQueries({ queryKey: qk.skills.gallery() }),
            ]
          : []),
      ]);
      if (useOrgStore.getState().activeOrgId === ownerOrg) onSaved?.();
    },
    onError: (error) => toast.error(getErrorMessage(error, errors)),
  };
  const save = {
    console_role_defaults: useMutation(saveOptions),
    console_notices: useMutation(saveOptions),
    chat_home_defaults: useMutation(saveOptions),
    chat_cost_visibility: useMutation(saveOptions),
    onboarding_reminders: useMutation(saveOptions),
  };
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
            disabled={save.console_role_defaults.isPending}
            onSave={(role, changes, onSaved) =>
              save.console_role_defaults.mutate({
                ownerOrg: org.id,
                changes: { console_role_defaults: { [role]: changes } },
                onSaved,
              })
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
            disabled={save.console_notices.isPending || !data}
            onChange={(console_notices) =>
              save.console_notices.mutate({ ownerOrg: org.id, changes: { console_notices } })
            }
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
          disabled={save.chat_home_defaults.isPending || !data}
          onChange={(field, value) =>
            save.chat_home_defaults.mutate({
              ownerOrg: org.id,
              changes: { chat_home_defaults: { [field]: value } },
            })
          }
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
          disabled={
            save.chat_cost_visibility.isPending || !data || data.costs?.availability === false
          }
          onChange={(chat_cost_visibility) =>
            save.chat_cost_visibility.mutate({
              ownerOrg: org.id,
              changes: { chat_cost_visibility },
            })
          }
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
          disabled={save.onboarding_reminders.isPending || !data}
          onChange={(onboarding_reminders) =>
            save.onboarding_reminders.mutate({
              ownerOrg: org.id,
              changes: { onboarding_reminders },
            })
          }
        />
      </ServiceCard>
    </>
  );
}
