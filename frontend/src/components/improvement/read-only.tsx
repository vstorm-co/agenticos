"use client";

import { createContext, useContext } from "react";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Why the wizard is only being read, when it is: the session is over for good,
 * or the reader may see it but not edit the agent. Every control that would
 * change the session, or spend on it, leaves itself out under either.
 */
export type ReadOnlyReason = "finished" | "viewOnly";

const ReadOnlyContext = createContext<ReadOnlyReason | null>(null);

export const ReadOnlyProvider = ReadOnlyContext.Provider;

/** Whether this part of the wizard is only being read. */
export function useReadOnly(): boolean {
  return useContext(ReadOnlyContext) !== null;
}

/** Says, once at the top of the wizard, why nothing in it can be changed. */
export function ReadOnlyNote() {
  const t = useTranslations("improvement.readOnly");
  const reason = useContext(ReadOnlyContext);
  if (reason === null) return null;
  return (
    <p role="status" className="bg-muted/50 flex items-start gap-2 rounded-xl border p-4 text-sm">
      <Lock className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden />
      {t(reason)}
    </p>
  );
}
