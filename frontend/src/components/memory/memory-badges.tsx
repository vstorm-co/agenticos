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
 * one. The raw `user:`/`chan:` key is shown for a private partition because it
 * is the only stable handle an operator has: naming the person behind it needs
 * an identity the key does not carry.
 */
export function PartitionBadge({ scopeKey }: { scopeKey: string | null }) {
  const t = useTranslations("memory");
  if (scopeKey === null) return <Badge variant="outline">{t("partitionShared")}</Badge>;
  return (
    <Badge variant="secondary" className="font-mono">
      {scopeKey}
    </Badge>
  );
}
