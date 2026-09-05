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
 * Whose memory a row is — the organisation's, one group chat's, or one person's.
 *
 * A person's store shows the resolved name the server attaches (`ownerLabel`, the
 * member's email) when it has one, with the raw key on hover; a key that did not
 * resolve — an unlinked chat account, a departed or non-member user — falls back
 * to the raw key, the only stable handle left. A room shows its key, which is the
 * channel, because the platform's own channel name is not ours to resolve.
 */
export function OwnerBadge({
  ownerKey,
  ownerLabel,
}: {
  ownerKey: string | null;
  ownerLabel?: string | null;
}) {
  const t = useTranslations("memory");
  if (ownerKey === null) return <Badge variant="outline">{t("ownerOrg")}</Badge>;
  if (ownerLabel) {
    return (
      <Badge variant="secondary" title={ownerKey}>
        {ownerLabel}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="font-mono">
      {ownerKey}
    </Badge>
  );
}
