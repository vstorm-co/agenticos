"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { reportShellFailure } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { takeShared } from "@/lib/mobile/shared";
import { useComposerIntentStore } from "@/stores";

/**
 * Take what the app is holding for a new message - shared with the phone app
 * by another app, or dropped on blobby or the Dock icon (#2097, #2305) - and
 * open the chat with it in the composer. Files that could not be carried over
 * are named in a toast; nothing held is nothing done.
 */
export function useOpenShared(): () => void {
  const router = useRouter();
  const share = useComposerIntentStore((state) => state.share);
  const t = useTranslations("mobile.share");
  return useCallback(() => {
    takeShared()
      .then((shared) => {
        if (shared === null) return;
        if (shared.refused.length > 0) {
          toast.warning(t("notAttached", { names: shared.refused.join(", ") }));
        }
        if (shared.files.length === 0 && !shared.text) return;
        share({ id: Date.now(), files: shared.files, text: shared.text || undefined });
        router.push("/chat");
      })
      .catch((error: unknown) => reportShellFailure("could not read what was shared", error));
  }, [router, share, t]);
}
