"use client";

import { useState } from "react";
import { Brain, CheckCircle2, GitBranch, SlidersHorizontal, UsersRound, Bot } from "lucide-react";
import { useTranslations } from "next-intl";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, ListCard, ListCardEmpty, SearchInput } from "@/components/ui";
import { useMyClaims } from "@/hooks/use-my-claims";
import { CLAIMS_PAGE_SIZE, type MemoryClaimFilters } from "@/lib/memory-api";
import { ClaimDetail } from "./claim-detail";
import { ClaimFilters, type Kind, type Scope } from "./claim-filters";
import { MemoryPager, MemoryRow } from "./memory-list";

export function MyClaims() {
  const t = useTranslations("pages.memory.claims");
  const view = useTranslations("pages.memory.browser");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("all");
  const [scope, setScope] = useState<Scope>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const filters: MemoryClaimFilters = {
    q: q.trim(),
    ...(kind === "all" ? {} : { kind }),
    ...(scope === "all" ? {} : { scope }),
  };
  const { page, isLoading, error, history, setHistory, skip, showPage, correct, retract } =
    useMyClaims(filters);
  const claim = page?.items.find((item) => item.id === selected);
  const narrowed = Boolean(q.trim() || kind !== "all" || scope !== "all");
  const reset = () => {
    setQ("");
    setKind("all");
    setScope("all");
  };
  return (
    <ListCard
      title={view("memories")}
      namedByPage
      fill
      counted={isLoading || !page ? null : view("count", { count: page.total })}
      contentClassName="p-0"
      headerTour="my-claims"
      controls={
        <>
          <SearchInput
            value={q}
            onChange={setQ}
            maxLength={200}
            placeholder={view("searchMemories")}
          />
          <ClaimFilters
            kind={kind}
            scope={scope}
            history={history}
            onKindChange={(next) => {
              setKind(next);
              setSelected(null);
            }}
            onScopeChange={setScope}
            onHistoryChange={setHistory}
          />
        </>
      }
    >
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={4} />
      ) : error || !page ? (
        <ErrorState />
      ) : page.items.length === 0 ? (
        <ListCardEmpty
          icon={narrowed ? SlidersHorizontal : Brain}
          title={view(narrowed ? "noMatches" : "emptyMemories")}
          description={view(narrowed ? "tryFilters" : "emptyMemoriesHint")}
          {...(narrowed ? { cta: { label: view("clearFilters"), onClick: reset } } : {})}
        />
      ) : (
        <ul className="divide-foreground/5 divide-y px-2">
          {page.items.map((item) => (
            <MemoryRow
              key={item.id}
              title={item.statement}
              icon={
                item.kind === "decision"
                  ? GitBranch
                  : item.kind === "preference"
                    ? SlidersHorizontal
                    : CheckCircle2
              }
              muted={item.status !== "current" && item.status !== "disputed"}
              onOpen={() => setSelected(item.id)}
            >
              <Badge variant="secondary" className="rounded-md px-1.5 text-[11px] font-normal">
                {view(
                  `type.${item.kind === "fact" || item.kind === "preference" || item.kind === "decision" ? item.kind : "other"}`,
                )}
              </Badge>
              <span className="inline-flex items-center gap-1.5">
                {item.scope === "profile" ? (
                  <UsersRound className="size-3" aria-hidden />
                ) : (
                  <Bot className="size-3" aria-hidden />
                )}
                {item.scope === "profile" ? t("scopeProfile") : (item.agent_name ?? t("anAgent"))}
              </span>
              {item.status !== "current" && (
                <Badge variant="outline" className="text-[11px]">
                  {t(`status.${item.status}`)}
                </Badge>
              )}
            </MemoryRow>
          ))}
        </ul>
      )}
      {page && !error && (
        <MemoryPager
          skip={skip}
          count={page.items.length}
          total={page.total}
          size={CLAIMS_PAGE_SIZE}
          onPage={showPage}
        />
      )}
      {claim && (
        <ClaimDetail
          key={claim.id}
          claim={claim}
          correct={correct}
          retract={retract}
          onClose={() => setSelected(null)}
        />
      )}
    </ListCard>
  );
}
