"use client";

import { CircleAlert, History, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { Alert, AlertDescription, Badge, Button, Spinner } from "@/components/ui";
import { useDraftKnowledgeGap, useKnowledgeGapDraftEstimate } from "@/hooks/use-knowledge-gaps";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";

interface KnowledgeGapDraftStatusProps {
  topic: KnowledgeGapTopic;
  /** Whether the caller may ask for a draft here; otherwise the state is shown alone. */
  editable: boolean;
  /** Offer a new draft of a current one too, not only of a stale one. */
  offerRedraft?: boolean;
}

/**
 * Where a topic's draft stands, and asking for one: a draft is written only when
 * somebody asks, so a topic without one offers it with what it costs. While it is
 * being written that is announced instead; a failed one offers another try; and a
 * draft older than a document added to the knowledge base since says so and
 * offers a new one. A current draft needs nothing here unless `offerRedraft`.
 */
export function KnowledgeGapDraftStatus({
  topic,
  editable,
  offerRedraft = false,
}: KnowledgeGapDraftStatusProps) {
  const t = useTranslations("knowledgeGaps");
  const draft = useDraftKnowledgeGap();
  const asking = draft.isPending && draft.variables === topic.id;
  const stale = topic.has_draft && topic.draft_stale === true;
  const failed = topic.draft_failed === true;
  const offer = !failed && (!topic.has_draft || stale || offerRedraft);
  const estimate = useKnowledgeGapDraftEstimate(topic.id, {
    enabled: editable && offer && !topic.drafting,
  });

  if (topic.drafting || asking) {
    return (
      <p role="status" className="text-muted-foreground flex items-center gap-2 text-xs">
        <Spinner className="size-3.5" aria-hidden />
        {t("drafting")}
      </p>
    );
  }
  if (!failed && !stale && !(editable && offer)) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {failed && (
        <Alert variant="destructive" className="py-2">
          <CircleAlert className="h-4 w-4" aria-hidden />
          <AlertDescription className="flex flex-wrap items-center gap-2 text-xs">
            {t("draftFailed")}
            {editable && (
              <Button size="sm" variant="outline" onClick={() => draft.mutate(topic.id)}>
                {t("retry")}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {stale && (
        <Badge variant="outline" className="h-auto whitespace-normal">
          <History className="h-3 w-3 shrink-0" aria-hidden />
          {t("draftStale")}
        </Badge>
      )}
      {editable && offer && (
        <DraftButton
          again={topic.has_draft}
          cost={estimate.estimate?.total_usd}
          onClick={() => draft.mutate(topic.id)}
        />
      )}
    </div>
  );
}

function DraftButton({
  again,
  cost,
  onClick,
}: {
  again: boolean;
  /** Absent while it is read, when reading it failed, or when the model has no price. */
  cost: string | null | undefined;
  onClick: () => void;
}) {
  const t = useTranslations("knowledgeGaps");
  const locale = useLocale();
  const values = { known: cost ? "yes" : "no", cost: cost ? usd(cost, locale) : "" };
  return (
    <Button size="sm" variant="outline" onClick={onClick}>
      <Sparkles className="h-3.5 w-3.5" aria-hidden />
      {again ? t("redraftAction", values) : t("draftAction", values)}
    </Button>
  );
}
