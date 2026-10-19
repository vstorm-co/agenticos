"use client";

import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { useRegroupKnowledgeGaps, type KnowledgeGapPanelScope } from "@/hooks/use-knowledge-gaps";
import { Perm } from "@/types/permissions";
import type { KnowledgeGapStatus } from "@/types/knowledge-gaps";

interface KnowledgeGapsToolbarProps {
  scope: KnowledgeGapPanelScope;
  status: KnowledgeGapStatus;
  onStatus: (status: KnowledgeGapStatus) => void;
}

/**
 * The list card's controls: which topics to show and, on a knowledge base's own
 * page, grouping its waiting questions now - gated as that page's other changes are.
 */
export function KnowledgeGapsToolbar({ scope, status, onStatus }: KnowledgeGapsToolbarProps) {
  const t = useTranslations("knowledgeGaps");
  const { can } = usePermissions();
  return (
    <div className="flex flex-wrap items-center gap-2">
      {scope.kind === "collection" && can(Perm.collectionsEdit) && (
        <RegroupButton knowledgeBaseId={scope.id} />
      )}
      <Select value={status} onValueChange={(next) => onStatus(next as KnowledgeGapStatus)}>
        <SelectTrigger className="w-36" aria-label={t("statusFilter")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="open">{t("statusOpen")}</SelectItem>
          <SelectItem value="dismissed">{t("statusDismissed")}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

function RegroupButton({ knowledgeBaseId }: { knowledgeBaseId: string }) {
  const t = useTranslations("knowledgeGaps");
  const regroup = useRegroupKnowledgeGaps(knowledgeBaseId);
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={regroup.isPending}
      onClick={() => regroup.mutate()}
    >
      <RefreshCw className="h-3.5 w-3.5" aria-hidden />
      {t("regroup")}
    </Button>
  );
}
