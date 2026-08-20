"use client";

import { useEffect, useState } from "react";
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
  ListCard,
  ListCardEmpty,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useKnowledgeBases, usePermissions, useUrlState } from "@/hooks";
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

type RagTab = "bases" | "search" | "integrations";

export default function RAGPage() {
  const t = useTranslations("pages.kb");
  const { kbs, isLoading, listError, fetchKBs } = useKnowledgeBases();
  const [createOpen, setCreateOpen] = useState(false);
  // Presentation, never enforcement - the server refuses regardless. A Viewer
  // holds `collections:view` only, and offering them a create button is
  // telling them to try something that cannot work.
  const { can } = usePermissions();
  const mayEdit = can(Perm.collectionsEdit);

  // The tab belongs in the URL, so a search is a link somebody can send - and
  // through `useUrlState` rather than reading `window` in a `useState`
  // initializer, which renders one value on the server and another in the
  // browser and costs a hydration mismatch: the bases flash before the named tab
  // appears.
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab: RagTab = tabParam === "search" || tabParam === "integrations" ? tabParam : "bases";
  const setTab = (next: RagTab) => setTabParam(next === "bases" ? null : next);

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
            <Button data-tour="knowledge-new" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("newKnowledgeBase")}
            </Button>
          ) : undefined
        }
      />

      {/* The shared underline strip - this page's look, now the primitive's.

          The root wraps the panels as well as the list: a trigger points at its
          panel with `aria-controls`, so a root closing after the list left those
          references dangling and the visible section with no `role="tabpanel"`.
          Pre-existing here; found reviewing the same change on the detail page. */}
      <Tabs value={tab} onValueChange={(next) => setTab(next as RagTab)}>
        <TabsList data-tour="knowledge-tabs">
          <TabsTrigger value="bases">{t("knowledgeBases")}</TabsTrigger>
          <TabsTrigger value="search">{t("search")}</TabsTrigger>
          {/* A page-level concern, so a tab beside the other two rather than a
              section below a grid three rows deep - and reachable without first
              choosing Knowledge bases (#939). */}
          <TabsTrigger value="integrations" data-tour="knowledge-tab-integrations">
            {t("integrations")}
          </TabsTrigger>
        </TabsList>

        {/* The scope selector is built from the base list, so a failed list is a
            failed search tab: handing it an empty array would have it say there
            is nothing to search, which is the list's own error wearing a fact's
            face. */}
        <TabsContent value="search">
          {loading ? (
            <Skeleton className="h-48 w-full rounded-xl" />
          ) : listError ? (
            <ErrorState
              title={t("listFailedTitle")}
              description={t("listFailedDescription")}
              cta={{ label: t("retry"), onClick: () => fetchKBs() }}
            />
          ) : (
            <SearchTab kbs={sorted} />
          )}
        </TabsContent>

        <TabsContent value="bases">
          <ListCard
            title={t("bases")}
            counted={loading || listError ? null : t("storedCount", { count: kbs.length })}
            contentClassName="p-4"
          >
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
              <ListCardEmpty
                icon={Database}
                title={t("noKnowledgeBasesYet")}
                description={mayEdit ? t("createOneGiveYour") : t("nothingHasBeenShared")}
                cta={
                  mayEdit
                    ? {
                        label: (
                          <>
                            <Plus className="h-3.5 w-3.5" />
                            {t("createKnowledgeBase")}
                          </>
                        ),
                        onClick: () => setCreateOpen(true),
                      }
                    : undefined
                }
              />
            ) : (
              <div className="grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {sorted.map((kb) => (
                  <KBCard key={kb.id} kb={kb} />
                ))}
              </div>
            )}
          </ListCard>
        </TabsContent>

        {/* The thing the collections are fed from: a connector configured once
            and cloned into each base that needs it. `targets` is the base list,
            so this tab needs it loaded - which is why it is the same query
            rather than a second one. */}
        <TabsContent value="integrations">
          <div data-tour="knowledge-integrations">
            <ReusableIntegrations targets={kbs} />
          </div>
        </TabsContent>
      </Tabs>

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
