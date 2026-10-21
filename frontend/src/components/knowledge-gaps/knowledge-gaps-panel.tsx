"use client";

import { useState } from "react";
import { SearchX } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  ListCard,
  ListCardEmpty,
  ListCardFootRow,
  PAGE_SIZE,
  PaginationBar,
} from "@/components/ui";
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
  const { topics, total, ungrouped, canRegroup, isLoading, error, refetch } = useKnowledgeGaps(
    scope,
    {
      status,
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    },
  );

  return (
    <>
      <ListCard
        title={t("title")}
        counted={isLoading ? null : t("topicCount", { count: total })}
        controls={
          <KnowledgeGapsToolbar
            scope={scope}
            canRegroup={canRegroup}
            status={status}
            onStatus={(next) => {
              setStatus(next);
              setPage(0);
            }}
          />
        }
        contentClassName="p-0"
      >
        <p className="border-border text-muted-foreground border-b px-4 py-3 text-xs sm:px-5">
          {scope.kind === "collection" ? t("descriptionCollection") : t("descriptionAgent")}{" "}
          {t("nothingAutomatic")}
        </p>
        {ungrouped > 0 && (
          <p className="border-border bg-muted/40 text-muted-foreground border-b px-4 py-2 text-xs sm:px-5">
            {t("ungrouped", { count: ungrouped })}
          </p>
        )}
        {isLoading ? (
          <div className="p-4 sm:p-5">
            <LoadingState variant="skeleton-list" rows={3} />
          </div>
        ) : error ? (
          <div className="p-4 sm:p-5">
            <ErrorState
              title={t("loadFailed")}
              description={t("loadFailedBody")}
              cta={{ label: t("retry"), onClick: () => void refetch() }}
            />
          </div>
        ) : topics.length === 0 ? (
          <ListCardEmpty
            icon={SearchX}
            title={status === "open" ? t("emptyOpen") : t("emptyDismissed")}
            description={status === "open" ? t("emptyOpenBody") : t("emptyDismissedBody")}
          />
        ) : (
          <>
            <ul className="divide-border divide-y">
              {topics.map((topic) => (
                <KnowledgeGapRow
                  key={topic.id}
                  topic={topic}
                  showKnowledgeBase={scope.kind === "agent"}
                  onOpen={() => setOpenTopic(topic.id)}
                />
              ))}
            </ul>
            {total > PAGE_SIZE && (
              <ListCardFootRow>
                <PaginationBar page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />
              </ListCardFootRow>
            )}
          </>
        )}
      </ListCard>
      {openTopic !== null && (
        <KnowledgeGapDialog topicId={openTopic} onClose={() => setOpenTopic(null)} />
      )}
    </>
  );
}
