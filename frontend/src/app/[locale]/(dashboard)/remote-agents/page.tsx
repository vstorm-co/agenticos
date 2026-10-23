"use client";

import { useState } from "react";
import { Network, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { RegisterRemoteAgentDialog } from "@/components/remote-agents/register-remote-agent-dialog";
import { RemoteAgentList } from "@/components/remote-agents/remote-agent-list";
import { ErrorState } from "@/components/states";
import { Button, ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useExternalAgents, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * Other vendors' agents this organization's agents may hand work to over A2A
 * (#2092). Registered once here, by the address of their agent card; picked per
 * agent in its delegation settings, beside the organization's own agents.
 *
 * Listing asks `agents:view` and registering `agents:edit`, as the API does.
 */
export default function RemoteAgentsPage() {
  const t = useTranslations("remoteAgents");
  const { agents, isLoading, error, register, refresh, remove } = useExternalAgents();
  const { can } = usePermissions();
  const canManage = can(Perm.agentsEdit);
  const [registering, setRegistering] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("pageDescription")}
        actions={
          canManage ? (
            <Button data-tour="remote-agents-register" onClick={() => setRegistering(true)}>
              <Plus className="h-4 w-4" />
              {t("register")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        data-tour="remote-agents-list"
        title={t("listTitle")}
        counted={
          isLoading || error !== null ? null : t("registeredCount", { count: agents.length })
        }
        contentClassName="p-0"
      >
        {isLoading ? (
          <div className="space-y-3 p-5">
            {[0, 1].map((row) => (
              <Skeleton key={row} className="h-12 w-full" />
            ))}
          </div>
        ) : error !== null ? (
          <ErrorState description={error} className="m-5" />
        ) : agents.length === 0 ? (
          <ListCardEmpty
            icon={Network}
            title={t("emptyTitle")}
            description={t("emptyDescription")}
          />
        ) : (
          <RemoteAgentList agents={agents} onRefresh={refresh} onRemove={remove} />
        )}
      </ListCard>

      <RegisterRemoteAgentDialog
        open={registering}
        onOpenChange={setRegistering}
        onSubmit={register}
      />
    </div>
  );
}
