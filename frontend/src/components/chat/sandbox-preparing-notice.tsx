"use client";

import { Box } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Says the run is waiting for its sandbox to open.
 *
 * The first session after an update builds the runtime's image on the sandbox
 * host, which takes minutes. During them no token streams and no tool step
 * opens, so without this the chat reads as broken - and a reload cancels the
 * turn that was about to start (#2222). It sits above the composer, beside the
 * summary notice, for the reason that one gives: it is not something the agent
 * said, and nothing here is kept.
 */
export function SandboxPreparingNotice() {
  const t = useTranslations("chat");
  return (
    <div
      className="text-muted-foreground mb-2 flex items-center gap-2 px-1 text-xs"
      role="status"
      aria-live="polite"
    >
      <Box className="h-3 w-3 animate-pulse" aria-hidden />
      {t("sandboxPreparing")}
    </div>
  );
}
