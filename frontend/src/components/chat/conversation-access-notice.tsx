"use client";

import { Loader2, LockKeyhole } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

/** Access states occupy the composer's place without offering an unusable draft. */
export function ConversationAccessNotice({
  state,
  onRetry,
  onContinue,
  continuing = false,
}: {
  state: "checking" | "error" | "view" | "routine";
  onContinue?: () => void;
  continuing?: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations("chat");
  const Icon = state === "checking" ? Loader2 : LockKeyhole;
  return (
    <div
      role="status"
      className="text-muted-foreground panel flex flex-wrap items-center justify-center gap-2 rounded-xl px-4 py-3 text-center text-sm"
    >
      <Icon
        aria-hidden
        className={cn(
          "h-4 w-4 shrink-0",
          state === "checking" && "animate-spin motion-reduce:animate-none",
        )}
      />
      <span>
        {t(
          state === "checking"
            ? "accessChecking"
            : state === "error"
              ? "accessFailed"
              : state === "routine"
                ? "routineHistoryReadOnly"
                : "conversationViewOnly",
        )}
      </span>
      {state === "routine" && onContinue && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onContinue}
          disabled={continuing}
        >
          {t("routineContinueChat")}
        </Button>
      )}
      {state === "error" && (
        <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
          {t("accessRetry")}
        </Button>
      )}
    </div>
  );
}
