"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight, Database, Lock, Plus, Sparkles, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { CreateKBDialog, ReusableIntegrations } from "@/components/kb";
import { SearchTab } from "@/components/rag/search-tab";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { useKnowledgeBases, usePermissions } from "@/hooks";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import type { KBScope, KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * How each scope is drawn: an icon, and the key to the word for it.
 *
 * A key rather than the word, because a table at module scope has no
 * translator to call - `KBCard` reads `t(labelKey)` at the point of use.
 */
const SCOPE_META: Record<KBScope, { labelKey: string; icon: LucideIcon }> = {
  personal: { labelKey: "scopePersonal", icon: Lock },
  org: { labelKey: "scopeOrg", icon: Users },
  app: { labelKey: "scopeApp", icon: Sparkles },
};

/**
 * The list's frame, drawn whether or not there is anything in it - the same
 * always-visible container the vault draws around its keys. Same header, same
 * border, in every state: what changes is what is inside it.
 */
function BasesCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.kb");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("bases")}</CardTitle>
          <CardDescription className="text-xs">
            {/* `null` is "the request has not answered". Rendering "0 knowledge
                bases" there would state something nothing has said yet. */}
            {count === null ? <Skeleton className="h-3 w-32" /> : t("storedCount", { count })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  );
}

type RagTab = "bases" | "search";

export default function RAGPage() {
  const t = useTranslations("pages.kb");
  const { kbs, isLoading, listError, fetchKBs } = useKnowledgeBases();
  const [createOpen, setCreateOpen] = useState(false);
  // Presentation, never enforcement - the server refuses regardless. A Viewer
  // holds `collections:view` only, and offering them a create button is
  // telling them to try something that cannot work.
  const { can } = usePermissions();
  const mayEdit = can(Perm.collectionsEdit);

  const [tab, setTabState] = useState<RagTab>(() => {
    if (typeof window !== "undefined") {
      if (new URLSearchParams(window.location.search).get("tab") === "search") return "search";
    }
    return "bases";
  });
  // The tab belongs in the URL, so a search is a link somebody can send.
  const setTab = (next: RagTab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "bases") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState({}, "", url.toString());
  };

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  // Default KB first, then newest first.
  const sorted = [...kbs].sort((a, b) => {
    if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  const loading = isLoading && kbs.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("knowledgeBases")}
        description={t("groupRelatedDocumentsInto")}
        actions={
          mayEdit ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("newKnowledgeBase")}
            </Button>
          ) : undefined
        }
      />

      <div className="border-border flex gap-6 border-b">
        {(["bases", "search"] as const).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "-mb-px border-b-2 px-1 pb-3 text-sm font-medium transition-colors",
              tab === id
                ? "border-foreground text-foreground"
                : "text-muted-foreground hover:text-foreground border-transparent",
            )}
          >
            {id === "bases" ? t("knowledgeBases") : t("search")}
          </button>
        ))}
      </div>

      {tab === "search" ? (
        // The scope selector is built from the base list, so a failed list is a
        // failed search tab: handing it an empty array would have it say there is
        // nothing to search, which is the list's own error wearing a fact's face.
        loading ? (
          <Skeleton className="h-48 w-full rounded-xl" />
        ) : listError ? (
          <ErrorState
            title={t("listFailedTitle")}
            description={t("listFailedDescription")}
            cta={{ label: t("retry"), onClick: () => fetchKBs() }}
          />
        ) : (
          <SearchTab kbs={sorted} />
        )
      ) : (
        <>
          <BasesCard count={loading || listError ? null : kbs.length}>
            {loading ? (
              // The same tiles the populated grid draws, as skeletons - a skeleton
              // that draws a different shape is a layout jump on every load.
              <div className="grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {[0, 1, 2].map((tile) => (
                  <div key={tile} className="border-border rounded-xl border p-5">
                    <Skeleton className="h-9 w-9 rounded-lg" />
                    <Skeleton className="mt-4 h-4 w-32" />
                    <Skeleton className="mt-2 h-3 w-full" />
                    <Skeleton className="mt-5 h-3 w-24" />
                  </div>
                ))}
              </div>
            ) : listError ? (
              // Not the empty state: "you have no bases" and "the request failed"
              // are different facts, and only one of them offers a create button.
              <ErrorState
                title={t("listFailedTitle")}
                description={t("listFailedDescription")}
                cta={{ label: t("retry"), onClick: () => fetchKBs() }}
              />
            ) : kbs.length === 0 ? (
              // Inline rather than an `EmptyState`: that component draws its own
              // bordered box, and inside a card it would frame one message twice.
              <div className="px-6 py-12 text-center">
                <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
                  <Database className="h-5 w-5" />
                </div>
                <p className="text-foreground mt-4 text-sm font-medium">
                  {t("noKnowledgeBasesYet")}
                </p>
                <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
                  {mayEdit ? t("createOneGiveYour") : t("nothingHasBeenShared")}
                </p>
                {mayEdit && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-5"
                    onClick={() => setCreateOpen(true)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {t("createKnowledgeBase")}
                  </Button>
                )}
              </div>
            ) : (
              <div className="grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {sorted.map((kb) => (
                  <KBCard key={kb.id} kb={kb} />
                ))}
              </div>
            )}
          </BasesCard>

          {/* Below the collections, because it is the thing they are fed from: a
          connector configured once and cloned into each base that needs it. */}
          <ReusableIntegrations targets={kbs} />
        </>
      )}

      <CreateKBDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={() => fetchKBs()} />
    </div>
  );
}

function KBCard({ kb }: { kb: KnowledgeBase }) {
  const t = useTranslations("pages.kb");
  const meta = SCOPE_META[kb.scope];

  // The class list below is a class list, not a message. It was in
  // `messages/en.json` as `groupBorderBorderBg2`, read through
  // `useTranslations` and handed to `cn()` - a translator opening `pl.json` was
  // being asked to translate Tailwind. Its leading `group` is gone with it: the
  // only `group-hover` in this file was on the delete button #303 removed, so
  // it named a relationship nothing was on the other end of.
  return (
    <div className="border-border bg-card hover:border-foreground/30 hover:bg-accent relative flex flex-col rounded-xl border transition-colors">
      {/* The card is a link and nothing else, so the layering is a link over
          content that declines the click rather than the three-way z-index
          argument this used to be. Deleting a collection now lives on the
          collection's own page, which is where you can see what it holds. */}
      <Link
        href={ROUTES.RAG_DETAIL(kb.id)}
        className="focus-visible:ring-ring absolute inset-0 rounded-[inherit] focus-visible:ring-2 focus-visible:outline-none"
        aria-label={t("openCollection", { name: kb.name })}
      />

      <div className="pointer-events-none flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-2">
          <span className="bg-muted text-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
            <meta.icon className="h-4 w-4" />
          </span>

          {kb.is_default && (
            <Badge variant="outline" className="border-border text-muted-foreground font-normal">
              {t("default")}
            </Badge>
          )}
        </div>

        <div className="mt-4 flex-1">
          <p className="text-foreground text-base leading-tight font-semibold">{kb.name}</p>
          {kb.description ? (
            <p className="text-muted-foreground mt-1.5 line-clamp-2 text-sm leading-relaxed">
              {kb.description}
            </p>
          ) : (
            <p className="text-muted-foreground mt-1.5 truncate font-mono text-xs">
              {kb.collection_name}
            </p>
          )}
        </div>

        <div className="text-muted-foreground mt-5 flex items-center justify-between gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 truncate">
            <meta.icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{t(meta.labelKey)}</span>
          </span>
          <ArrowUpRight className="h-4 w-4 shrink-0" />
        </div>
      </div>
    </div>
  );
}
