"use client";

import { AlertCircle, CheckCircle2, CircleSlash, Clock, Loader2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ragStatus } from "@/lib/rag-status";
import type { RAGStatusTone } from "@/lib/rag-status";
import { cn } from "@/lib/utils";

/** How each tone is drawn. Keyed by tone so a new status needs no entry here. */
const TONE_ICON: Record<RAGStatusTone, { Icon: LucideIcon; spin: boolean }> = {
  progress: { Icon: Loader2, spin: true },
  success: { Icon: CheckCircle2, spin: false },
  failure: { Icon: AlertCircle, spin: false },
  cancelled: { Icon: CircleSlash, spin: false },
  unknown: { Icon: Clock, spin: false },
};

/**
 * A document's or a sync source's status, as a word and a colour.
 *
 * One component for both, because two of them is what let them disagree: this
 * was a document badge mapping `completed`/`pending`/`failed` and a sync badge
 * testing `failed`, and the worker writes none of those four (#356). Both now
 * ask `ragStatus`, and a failed anything is `text-destructive` rather than the
 * same muted grey as a finished one.
 */
export function RagStatusBadge({
  status,
  message,
  className,
}: {
  status: string;
  message: string | null;
  className?: string;
}) {
  const t = useTranslations("ragStatus");
  const { words, tone } = ragStatus(status);
  const { Icon, spin } = TONE_ICON[tone];
  return (
    <Badge
      variant="outline"
      title={message ?? undefined}
      className={cn(
        "border-border gap-1 font-normal",
        tone === "failure" ? "text-destructive" : "text-muted-foreground",
        className,
      )}
    >
      <Icon className={cn("h-3 w-3", spin && "animate-spin")} />
      {words === null ? status : t(words)}
    </Badge>
  );
}
