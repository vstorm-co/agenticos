"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** One attention label across the Inbox, briefing and conversation previews. */
export function SuggestionPriority({ className }: { className?: string }) {
  const t = useTranslations("chat.suggestions");
  return (
    <Badge
      data-suggestion-priority
      variant="warning"
      className={cn("shrink-0 px-2 py-0 text-[11px]", className)}
    >
      {t("urgent")}
    </Badge>
  );
}
