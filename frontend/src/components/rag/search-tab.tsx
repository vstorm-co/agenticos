"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Database, FileText, Search } from "lucide-react";

import {
  Badge,
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { useChanged } from "@/hooks/use-changed";
import { ROUTES } from "@/lib/constants";
import { searchDocuments, type RAGSearchResult } from "@/lib/rag-api";
import { useOrgStore } from "@/stores";
import type { KnowledgeBase } from "@/types";

const ALL_BASES = "__all__";
const RESULT_LIMIT = 10;

type SearchStatus = "idle" | "searching" | "done" | "error";

interface SearchTabProps {
  /** The knowledge bases the caller can read; the search scope options. */
  kbs: KnowledgeBase[];
}

/**
 * Semantic search across the caller's knowledge bases.
 *
 * The scope defaults to every readable base because "where did the agent get
 * that" rarely comes with a collection name attached. Each result carries the
 * base it came from, its source document, page and score - enough for a human
 * to judge the chunk without opening anything.
 */
export function SearchTab({ kbs }: SearchTabProps) {
  const t = useTranslations("rag.search");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<string>(ALL_BASES);
  const [results, setResults] = useState<RAGSearchResult[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [tookMs, setTookMs] = useState(0);

  // Results from one organization mean nothing inside the next; a scope picked
  // there may not even exist here.
  if (useChanged(orgId)) {
    setQuery("");
    setScope(ALL_BASES);
    setResults([]);
    setStatus("idle");
  }

  // Several bases may share one physical collection, so names are deduplicated on
  // the way out and a result maps back to the first base claiming its collection.
  const collectionNames = (selected: string): string[] => {
    const chosen = selected === ALL_BASES ? kbs : kbs.filter((kb) => kb.id === selected);
    return [...new Set(chosen.map((kb) => kb.collection_name))];
  };
  const baseFor = (collection: unknown): KnowledgeBase | undefined =>
    kbs.find((kb) => kb.collection_name === collection);

  const runSearch = async () => {
    const trimmed = query.trim();
    const names = collectionNames(scope);
    if (!trimmed || names.length === 0) return;
    const startedIn = orgId;
    setStatus("searching");
    const startedAt = performance.now();
    try {
      const data = await searchDocuments({
        query: trimmed,
        collection_names: names,
        limit: RESULT_LIMIT,
      });
      // An answer that lands after an organization switch describes documents
      // the active tenant does not have.
      if ((useOrgStore.getState().activeOrgId ?? "") !== startedIn) return;
      setResults(data.results);
      setTookMs(Math.round(performance.now() - startedAt));
      setStatus("done");
    } catch {
      if ((useOrgStore.getState().activeOrgId ?? "") !== startedIn) return;
      setResults([]);
      setStatus("error");
    }
  };

  if (kbs.length === 0) {
    return (
      <div className="border-border bg-card text-muted-foreground flex flex-col items-center justify-center rounded-xl border py-16 text-center">
        <Database className="mb-3 h-8 w-8" />
        <p className="text-sm">{t("noBases")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="border-border bg-card rounded-xl border p-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            placeholder={t("placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            className="rounded-xl"
          />
          <div className="flex gap-2">
            <Select value={scope} onValueChange={setScope}>
              <SelectTrigger className="w-full rounded-xl sm:w-56" aria-label={t("scopeLabel")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_BASES}>{t("allBases")}</SelectItem>
                {kbs.map((kb) => (
                  <SelectItem key={kb.id} value={kb.id}>
                    {kb.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              onClick={runSearch}
              disabled={status === "searching" || !query.trim()}
              className="rounded-xl"
            >
              <Search className="mr-2 h-4 w-4" />
              {status === "searching" ? t("searching") : t("button")}
            </Button>
          </div>
        </div>
      </div>

      {/* A failed search and an empty answer are different facts, and only one
          of them should suggest rephrasing the query. */}
      {status === "error" && (
        <ErrorState
          title={t("failedTitle")}
          description={t("failedDescription")}
          cta={{ label: t("retry"), onClick: () => void runSearch() }}
        />
      )}

      {status === "done" && (
        <p className="text-muted-foreground text-xs" role="status">
          {t("resultCount", { count: results.length, ms: tookMs })}
        </p>
      )}

      {status === "done" && results.length === 0 && (
        <div className="border-border bg-card flex flex-col items-center justify-center rounded-xl border py-12 text-center">
          <Search className="text-muted-foreground mb-3 h-8 w-8" />
          <p className="text-foreground text-sm font-medium">{t("noResults")}</p>
          <p className="text-muted-foreground mt-1 text-xs">{t("noResultsHint")}</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          {results.map((result, i) => {
            const source = baseFor(result.metadata?.collection);
            return (
              <div key={i} className="border-border bg-card rounded-xl border p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <FileText className="text-muted-foreground h-3.5 w-3.5" />
                  <span className="text-foreground text-xs font-medium">
                    {String(result.metadata?.filename ?? "?")}
                  </span>
                  {result.metadata?.page_num != null && (
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {t("page", { page: String(result.metadata.page_num) })}
                    </Badge>
                  )}
                  {source && (
                    <Link
                      href={ROUTES.RAG_DETAIL(source.id)}
                      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-[10px] font-medium"
                    >
                      <Database className="h-3 w-3" />
                      {source.name}
                    </Link>
                  )}
                  <Badge variant="secondary" className="ml-auto font-mono text-[10px]">
                    {result.score.toFixed(3)}
                  </Badge>
                </div>
                <p className="text-muted-foreground text-sm leading-relaxed">{result.content}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
