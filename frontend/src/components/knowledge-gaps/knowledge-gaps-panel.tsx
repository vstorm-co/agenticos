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
import { CheckAnswersAiOff } from "./knowledge-gaps-check";
import { KnowledgeGapsToolbar } from "./knowledge-gaps-toolbar";

const EMPTY = {
  open: { title: "emptyOpen", body: "emptyOpenBody" },
  covered: { title: "emptyCovered", body: "emptyCoveredBody" },
  dismissed: { title: "emptyDismissed", body: "emptyDismissedBody" },
} as const satisfies Record<KnowledgeGapStatus, { title: string; body: string }>;

/**
 * What agents searched for and did not find, grouped into topics.
 *
 * Nothing is ingested on its own: a topic that needs a document is closed by a
 * person adding its content from the topic, or a document of their own.
 */
export function KnowledgeGapsPanel({
  scope,
  topicId,
  onTopicChange,
  status: heldStatus,
  onStatusChange,
}: {
  scope: KnowledgeGapPanelScope;
  /** The open topic, held by a page that keeps it in its URL; the panel holds its own otherwise. */
  topicId?: string | null;
  onTopicChange?: (topicId: string | null) => void;
  /** The status shown, held the same way as the topic. */
  status?: KnowledgeGapStatus;
  onStatusChange?: (status: KnowledgeGapStatus) => void;
}) {
  const t = useTranslations("knowledgeGaps");
  const [ownStatus, setOwnStatus] = useState<KnowledgeGapStatus>("open");
  const status = onStatusChange ? (heldStatus ?? "open") : ownStatus;
  const setStatus = onStatusChange ?? setOwnStatus;
  const [page, setPage] = useState(0);
  const [ownTopic, setOwnTopic] = useState<string | null>(null);
  const openTopic = onTopicChange ? (topicId ?? null) : ownTopic;
  const setOpenTopic = onTopicChange ?? setOwnTopic;
  const { topics, total, ungrouped, canRegroup, unchecked, isLoading, error, refetch } =
    useKnowledgeGaps(scope, {
      status,
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    });

  return (
    <>
      <ListCard
        title={t("title")}
        counted={isLoading ? null : t("topicCount", { count: total })}
        controls={
          <KnowledgeGapsToolbar
            scope={scope}
            canRegroup={canRegroup}
            unchecked={unchecked}
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
        {canRegroup && <CheckAnswersAiOff unchecked={unchecked} />}
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
            title={t(EMPTY[status].title)}
            description={t(EMPTY[status].body)}
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
