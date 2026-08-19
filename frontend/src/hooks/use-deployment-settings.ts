"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import type { BrandingResponse, NoticeLevel, SignupMode } from "@/lib/branding";
import { qk } from "@/lib/query-keys";

/**
 * This deployment's settings, as its administrator reads and writes them.
 *
 * The read is the whole form in one request; the write is a PATCH, so editing the
 * name does not resend - or silently clear - the announcement. `null` for a field
 * is a **deliberate clear**: the backend keeps it, and the renderer falls back to
 * the built-in. That is why every field here is `string | null` rather than
 * optional, and why the form sends the fields it touched rather than all of them.
 *
 * Images are their own mutations because they carry bytes rather than JSON, and
 * their storage paths are not in the update shape at all - the server writes those
 * itself. A caller who could name one could point this deployment's public logo at
 * anything the storage backend holds.
 */

export interface DeploymentSettings extends BrandingResponse {
  announcement: string | null;
  announcement_level: NoticeLevel;
  updated_at: string | null;
}

export interface DeploymentSettingsPatch {
  app_name?: string | null;
  tagline?: string | null;
  description?: string | null;
  footer_text?: string | null;
  terms_url?: string | null;
  privacy_url?: string | null;
  signup_mode?: SignupMode;
  allowed_email_domains?: string[];
  announcement?: string | null;
  announcement_level?: NoticeLevel;
  maintenance_mode?: boolean;
  maintenance_message?: string | null;
}

/** Which of the two marks an upload replaces. */
export type BrandingImage = "logo" | "favicon";

export function useDeploymentSettings() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.admin");
  const queryClient = useQueryClient();

  const settings = useQuery({
    queryKey: qk.admin.settings(),
    queryFn: () => apiClient.get<DeploymentSettings>("/admin/settings"),
  });

  // The whole app reads the branding from a server-resolved context, so a saved
  // change is only on screen after the server renders again. `router.refresh()`
  // belongs to the page that has a router; this invalidates the form's own copy.
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.admin.settings() }),
    [queryClient],
  );

  const save = useMutation({
    mutationFn: (patch: DeploymentSettingsPatch) =>
      apiClient.patch<DeploymentSettings>("/admin/settings", patch),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("settingsSaved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const uploadImage = useMutation({
    mutationFn: ({ kind, file }: { kind: BrandingImage; file: File }) =>
      apiClient.upload<DeploymentSettings>(`/admin/settings/${kind}`, file),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("imageUploaded"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const clearImage = useMutation({
    mutationFn: (kind: BrandingImage) =>
      apiClient.delete<DeploymentSettings>(`/admin/settings/${kind}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("imageCleared"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    settings: settings.data ?? null,
    isLoading: settings.isPending,
    error: settings.error,
    refetch: invalidate,
    save,
    uploadImage,
    clearImage,
  };
}
