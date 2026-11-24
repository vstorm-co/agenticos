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
import { useRegroupKnowledgeGaps, type KnowledgeGapPanelScope } from "@/hooks/use-knowledge-gaps";
import type { KnowledgeGapStatus } from "@/types/knowledge-gaps";
import { CheckAnswersButton } from "./knowledge-gaps-check";

interface KnowledgeGapsToolbarProps {
  scope: KnowledgeGapPanelScope;
  /** Whether the server lets the caller change this knowledge base, a grant included. */
  canRegroup: boolean;
  /** Recent answers on a knowledge base's page that no model has read for gaps yet. */
  unchecked: number;
  status: KnowledgeGapStatus;
  onStatus: (status: KnowledgeGapStatus) => void;
}

/**
 * The list card's controls: which topics to show and, on a knowledge base's own
 * page, grouping its waiting questions now and checking its answers - for
 * whoever may change that base.
 */
export function KnowledgeGapsToolbar({
  scope,
  canRegroup,
  unchecked,
  status,
  onStatus,
}: KnowledgeGapsToolbarProps) {
  const t = useTranslations("knowledgeGaps");
  return (
    <div className="flex flex-wrap items-center gap-2">
      {scope.kind === "collection" && canRegroup && (
        <>
          <CheckAnswersButton knowledgeBaseId={scope.id} unchecked={unchecked} />
          <RegroupButton knowledgeBaseId={scope.id} />
        </>
      )}
      <Select value={status} onValueChange={(next) => onStatus(next as KnowledgeGapStatus)}>
        <SelectTrigger className="w-36" aria-label={t("statusFilter")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="open">{t("statusOpen")}</SelectItem>
          <SelectItem value="covered">{t("statusCovered")}</SelectItem>
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
