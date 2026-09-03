"use client";

import { Badge } from "@/components/ui";
import type { MemoryOrigin } from "@/types/memory";
import { useTranslations } from "next-intl";

/**
 * Who authored a memory row, which is the same thing as whether it is trusted.
 *
 * An operator file is injectable (spliced into instructions like context); an
 * agent-written one is never injected, only read back through a tool. The badge
 * is the only place that distinction is visible before opening the row, so it is
 * filled for operator and quiet outline for agent — trust set in the louder
 * register.
 */
export function OriginBadge({ origin }: { origin: MemoryOrigin }) {
  const t = useTranslations("memory");
  return (
    <Badge variant={origin === "operator" ? "secondary" : "outline"}>
      {t(origin === "operator" ? "originOperator" : "originAgent")}
    </Badge>
  );
}

/**
 * Which partition a row lives in — the shared store, or one end-user's private
 * one. A private partition shows the resolved name the server attaches
 * (`partitionLabel`, the member's email) when it has one, with the raw
 * `user:`/`chan:` key on hover; a key that did not resolve — a channel account, a
 * departed or non-member user — falls back to the raw key, the only stable handle
 * left.
 */
export function PartitionBadge({
  scopeKey,
  partitionLabel,
}: {
  scopeKey: string | null;
  partitionLabel?: string | null;
}) {
  const t = useTranslations("memory");
  if (scopeKey === null) return <Badge variant="outline">{t("partitionShared")}</Badge>;
  if (partitionLabel) {
    return (
      <Badge variant="secondary" title={scopeKey}>
        {partitionLabel}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="font-mono">
      {scopeKey}
    </Badge>
  );
}
