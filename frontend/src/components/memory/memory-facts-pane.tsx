"use client";

import { useState } from "react";
import { Info, Plus, Sparkles, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  Alert,
  AlertDescription,
  Button,
  ConfirmDialog,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { OriginBadge, PartitionBadge } from "@/components/memory/memory-badges";
import { CreateMemoryFactDialog } from "@/components/memory/create-memory-fact-dialog";
import { useMemoryDangerZone, useMemoryFacts } from "@/hooks/use-memory";
import { getErrorMessage } from "@/lib/api-error";
import type { MemoryFact } from "@/types/memory";

interface MemoryFactsPaneProps {
  agentId: string;
  canEdit: boolean;
  /** The partition the whole Memory tab is filtered to; owned by the panel.
   * `all`/`shared`/`per_user`, or a specific `user:<id>` key. */
  scope: string;
}

/**
 * The facts half of the Memory tab.
 *
 * Facts are recalled by meaning. The agent writes them at runtime; an operator may
 * also seed one directly here (embedded server-side), but there is no edit — a fact
 * is replaced, not amended. The filter is a plain substring match, not the runtime
 * semantic recall — a query an operator typed would embed off the run's spend
 * ledger, which the intro says out loud.
 */
export function MemoryFactsPane({ agentId, canEdit, scope }: MemoryFactsPaneProps) {
  const t = useTranslations("memory");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const format = useFormatter();

  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);

  const { clearFacts } = useMemoryDangerZone(agentId);
  const { facts, total, isLoading, error, refetch, remove } = useMemoryFacts({
    agentId,
    scope,
    search,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  const [pendingDelete, setPendingDelete] = useState<MemoryFact | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isFiltering = search.trim() !== "";

  // Forgetting the last fact on a later page empties it and hides the pager,
  // stranding the operator on a blank page; step back to the last page with rows,
  // adjusting during render (React's guarded pattern) rather than in an effect
  // (codex).
  if (page > 0 && page >= pageCount) setPage(pageCount - 1);

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <SearchInput
        value={query}
        onChange={(next) => {
          setQuery(next);
          setPage(0);
        }}
        placeholder={t("filterFacts")}
        className="sm:w-56"
      />
      <Button size="sm" onClick={() => setCreateOpen(true)}>
        <Plus className="h-4 w-4" />
        {t("newFact")}
      </Button>
      {canEdit && total > 0 && (
        <Button variant="outline" size="sm" onClick={() => setClearOpen(true)}>
          {t("clearFacts")}
        </Button>
      )}
    </div>
  );

  return (
    <>
      <Alert className="mb-4">
        <Info className="h-4 w-4" />
        <AlertDescription>{t("factsIntro")}</AlertDescription>
      </Alert>

      <ListCard
        title={t("facts")}
        counted={error ? null : t("factCount", { count: total })}
        controls={controls}
      >
        {error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : isLoading ? (
          <LoadingState variant="skeleton-cards" rows={3} />
        ) : facts.length === 0 ? (
          <ListCardEmpty
            icon={Sparkles}
            title={isFiltering ? t("noFactMatches") : t("noFactsYet")}
            description={isFiltering ? t("noFactMatchesHint") : t("noFactsHint")}
          />
        ) : (
          <div className="space-y-4">
            <ul className="divide-border divide-y">
              {facts.map((fact) => (
                <li key={fact.id} className="flex items-start justify-between gap-3 py-3">
                  <div className="min-w-0 space-y-1.5">
                    <p className="text-foreground text-sm">{fact.content}</p>
                    <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                      <OriginBadge origin={fact.origin} />
                      <PartitionBadge
                        scopeKey={fact.end_user_scope_key}
                        partitionLabel={fact.partition_label}
                      />
                      {fact.created_at !== null && (
                        <span>
                          {t("remembered", {
                            when: format.relativeTime(new Date(fact.created_at)),
                          })}
                        </span>
                      )}
                    </div>
                  </div>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-destructive h-8 w-8 shrink-0"
                      aria-label={t("forgetFact")}
                      onClick={() => setPendingDelete(fact)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            <Pager
              page={page}
              pageCount={pageCount}
              matched={total}
              total={total}
              onPage={setPage}
              counted={t("factCount", { count: total })}
            />
          </div>
        )}
      </ListCard>

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={t("forgetFactConfirm")}
          description={t("forgetFactHint")}
          confirmLabel={t("forget")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}

      {clearOpen && (
        <ConfirmDialog
          open
          onOpenChange={() => setClearOpen(false)}
          title={t("clearFactsConfirm")}
          description={t("clearFactsHint")}
          confirmLabel={t("clearFacts")}
          destructive
          loading={clearFacts.isPending}
          onConfirm={async () => {
            await clearFacts.mutateAsync();
            setClearOpen(false);
          }}
        />
      )}

      <CreateMemoryFactDialog
        agentId={agentId}
        open={createOpen}
        onOpenChange={setCreateOpen}
        canEdit={canEdit}
      />
    </>
  );
}
