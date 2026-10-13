"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { AgentTemplateCatalog, TemplateInstallResult } from "@/types/providers";

/**
 * The shipped agent templates, and installing one.
 *
 * `enabled` on the dialog being open: the catalog is two dozen rows behind a
 * button, and a page that never opens it should not pay for them.
 */
export function useAgentTemplates(
  enabled: boolean,
  onInstalled?: (result: TemplateInstallResult) => void,
) {
  const t = useTranslations("agentTemplates");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: qk.agents.templates(),
    queryFn: () => apiClient.get<AgentTemplateCatalog>("/agents/templates"),
    enabled,
  });

  const install = useMutation({
    mutationFn: (key: string) =>
      apiClient.post<TemplateInstallResult>("/agents/templates/install", { key }),
    onSuccess: async (result) => {
      // Skills too: installing a template installs the gallery skills it binds.
      await queryClient.invalidateQueries({ queryKey: qk.agents.all() });
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      toast.success(t("installed", { name: result.name }));
      onInstalled?.(result);
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    industries: query.data?.industries ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    // `mutate`, not `mutateAsync`: nothing awaits this at the click site, and a
    // rejected promise nobody catches is an unhandled rejection.
    install: install.mutate,
    isInstalling: install.isPending,
    installingKey: install.variables,
  };
}
