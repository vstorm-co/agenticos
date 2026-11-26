"use client";

import Link from "next/link";
import { useState } from "react";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";

/** Keep a failed listing distinct from an empty workspace, without exposing transport jargon first. */
export function WorkspaceReadNotice({
  detail,
  failed,
  cloud,
  onRetry,
  code,
}: {
  detail: string;
  failed: boolean;
  cloud: boolean;
  onRetry: () => Promise<void>;
  code?: "workspace_not_retained" | null;
}) {
  const t = useTranslations("chat.files");
  const common = useTranslations("common");
  const errors = useTranslations("errors");
  const { can } = usePermissions();
  const [pending, setPending] = useState(false);
  const notRetained = code === "workspace_not_retained";
  const retry = async () => {
    setPending(true);
    try {
      await onRetry();
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, errors));
    } finally {
      setPending(false);
    }
  };
  return (
    <div
      role={failed ? "alert" : "status"}
      className="border-border bg-muted/40 rounded-xl border p-4"
    >
      <div className="flex items-start gap-2.5">
        <Info className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-medium">
            {t(notRetained ? "workspaceNotRetained" : failed ? "loadFailed" : "notAvailable")}
          </p>
          <p className="text-muted-foreground text-xs leading-5">
            {t(notRetained ? "workspaceNotRetainedBody" : "readNoticeBody")}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              loading={pending}
              onClick={() => void retry()}
            >
              {common("retry")}
            </Button>
            {cloud && !notRetained && can(Perm.connectionsManage) && (
              <Link href="/sandboxes" className="text-brand text-xs underline underline-offset-4">
                {t("connectionSettings")}
              </Link>
            )}
          </div>
          <NativeDisclosure className="pt-1">
            <summary className="text-muted-foreground text-xs">{t("technicalDetails")}</summary>
            <p className="text-muted-foreground mt-2 text-xs leading-5 break-words whitespace-pre-wrap">
              {detail}
            </p>
          </NativeDisclosure>
        </div>
      </div>
    </div>
  );
}
