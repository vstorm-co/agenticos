"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { GalleryInstallResult, SkillGallery } from "@/types/providers";

/**
 * The opt-in skill gallery, and installing from it.
 *
 * `enabled` rather than an unconditional fetch: the gallery is seventy rows
 * behind a button, and a page that never opens the dialog should not pay for
 * them.
 */
export function useSkillGallery(enabled: boolean) {
  const t = useTranslations("skills.gallery");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: qk.skills.gallery(),
    queryFn: () => apiClient.get<SkillGallery>("/skills/gallery"),
    enabled,
  });

  const install = useMutation({
    mutationFn: (keys: string[]) =>
      apiClient.post<GalleryInstallResult>("/skills/gallery/install", { keys }),
    onSuccess: async (result) => {
      // Both lists, because installing a shelf where some are present is the
      // normal case and a bare success count would read as a partial failure.
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      if (result.installed.length > 0) {
        toast.success(t("installed", { count: result.installed.length }));
      }
      if (result.installed.length === 0 && result.skipped.length > 0) {
        toast.info(t("allPresent", { count: result.skipped.length }));
      }
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    industries: query.data?.industries ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    // `mutate`, not `mutateAsync`: nothing awaits this at the call site, and a
    // rejected promise nobody catches is an unhandled rejection. `onError`
    // already shows the refusal.
    install: install.mutate,
    isInstalling: install.isPending,
    installingKeys: install.variables ?? [],
  };
}
