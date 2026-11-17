"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import type { MessageJumpState } from "@/hooks/use-message-jump";

export function MessageJumpNotice({ jump }: { jump: MessageJumpState }) {
  const t = useTranslations("chat.messageJump");
  const common = useTranslations("common");
  if (jump.status === "idle" || jump.status === "found") return null;
  return (
    <div
      role={jump.status === "loading" ? "status" : "alert"}
      className="bg-muted/40 flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2 text-sm"
    >
      <span className="min-w-0 flex-1">{t(jump.status)}</span>
      {jump.status === "failed" && (
        <Button type="button" variant="outline" size="sm" onClick={jump.retry}>
          {common("retry")}
        </Button>
      )}
      <Button type="button" variant="ghost" size="sm" onClick={jump.cancel}>
        {jump.status === "loading" ? t("cancel") : common("close")}
      </Button>
    </div>
  );
}
