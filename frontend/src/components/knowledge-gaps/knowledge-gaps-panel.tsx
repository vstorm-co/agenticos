"use client";

import { useState } from "react";
import { SearchX } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { PAGE_SIZE, PaginationBar } from "@/components/ui";
import { useKnowledgeGaps, type KnowledgeGapPanelScope } from "@/hooks/use-knowledge-gaps";
import type { KnowledgeGapStatus } from "@/types/knowledge-gaps";
import { KnowledgeGapDialog } from "./knowledge-gap-dialog";
import { KnowledgeGapRow } from "./knowledge-gap-row";
import { KnowledgeGapsToolbar } from "./knowledge-gaps-toolbar";

/**
 * What agents searched for and did not find, grouped into topics.
 *
 * Read-only towards the knowledge base: nothing here ingests anything, so a
 * topic that needs a document is closed by a person adding that document.
 */
export function KnowledgeGapsPanel({ scope }: { scope: KnowledgeGapPanelScope }) {
  const t = useTranslations("knowledgeGaps");
  const [status, setStatus] = useState<KnowledgeGapStatus>("open");
  const [page, setPage] = useState(0);
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  const { topics, total, ungrouped, isLoading, error, refetch } = useKnowledgeGaps(scope, {
    status,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  return (
    <div className="space-y-4">
      <KnowledgeGapsToolbar
        scope={scope}
        status={status}
        onStatus={(next) => {
          setStatus(next);
          setPage(0);
        }}
      />
      {ungrouped > 0 && (
        <p className="border-border bg-muted/40 text-muted-foreground rounded-lg border px-3 py-2 text-sm">
          {t("ungrouped", { count: ungrouped })}
        </p>
      )}
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : error ? (
        <ErrorState
          title={t("loadFailed")}
          description={t("loadFailedBody")}
          cta={{ label: t("retry"), onClick: () => void refetch() }}
        />
      ) : topics.length === 0 ? (
        <EmptyState
          icon={SearchX}
          title={status === "open" ? t("emptyOpen") : t("emptyDismissed")}
          description={status === "open" ? t("emptyOpenBody") : t("emptyDismissedBody")}
        />
      ) : (
        <>
          <ul className="border-border divide-border divide-y rounded-xl border">
            {topics.map((topic) => (
              <KnowledgeGapRow
                key={topic.id}
                topic={topic}
                showKnowledgeBase={scope.kind === "agent"}
                onOpen={() => setOpenTopic(topic.id)}
              />
            ))}
          </ul>
          <PaginationBar page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />
        </>
      )}
      {openTopic !== null && (
        <KnowledgeGapDialog topicId={openTopic} onClose={() => setOpenTopic(null)} />
      )}
    </div>
  );
}
