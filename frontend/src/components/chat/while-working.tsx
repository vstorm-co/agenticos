"use client";

import { CornerDownRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import type { SteerDraft } from "@/hooks/use-chat";

/** Corrections on their way to the running turn, until the model has them. */
export function WaitingSteers({ steers }: { steers: SteerDraft[] }) {
  const t = useTranslations("chat.whileWorking");
  if (steers.length === 0) return null;
  return (
    <div className="border-border bg-card mb-2 rounded-2xl border px-3 py-2">
      <p className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        {t("steersWaiting")}
      </p>
      <ul className="space-y-1">
        {steers.map((steer) => (
          <li key={steer.id} className="flex items-start gap-2 text-sm">
            <CornerDownRight className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="line-clamp-2 break-words">{steer.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
