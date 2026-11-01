"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { SystemAgentKind } from "@/types/agents";

/** That only the platform runs this agent, and which kind of work it does for it. */
export function SystemAgentBadge({ kind }: { kind: SystemAgentKind }) {
  const t = useTranslations("agents");
  return (
    <Badge variant="secondary" className="font-normal" title={t("systemAgentBadgeHint")}>
      {t("systemAgentBadge", { kind })}
    </Badge>
  );
}
