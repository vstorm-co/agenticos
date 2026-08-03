"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight, Database, Lock, Plus, Sparkles, Trash2, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { CreateKBDialog, ReusableIntegrations } from "@/components/kb";
import { PageHeader } from "@/components/dashboard/page-header";
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

const SCOPE_META: Record<KBScope, { label: string; icon: LucideIcon }> = {
  personal: { label: "Personal", icon: Lock },
  org: { label: "Organization", icon: Users },
  app: { label: "App-wide", icon: Sparkles },
};

/** How many bases there are, in words rather than a bare digit. */
function storedCount(count: number): string {
  return count === 1 ? "1 knowledge base" : `${count} knowledge bases`;
}

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
            {count === null ? <Skeleton className="h-3 w-32" /> : storedCount(count)}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  );
}

export default function KBPage() {
  const t = useTranslations("pages.kb");
  const { kbs, isLoading, fetchKBs, deleteKB } = useKnowledgeBases();
  const [createOpen, setCreateOpen] = useState(false);
  // Presentation, never enforcement - the server refuses regardless. A Viewer
  // holds `collections:view` only, and offering them a create button is
  // telling them to try something that cannot work.
  const { can } = usePermissions();
  const mayEdit = can(Perm.collectionsEdit);

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

      <BasesCard count={loading ? null : kbs.length}>
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
        ) : kbs.length === 0 ? (
          // Inline rather than an `EmptyState`: that component draws its own
          // bordered box, and inside a card it would frame one message twice.
          <div className="px-6 py-12 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <Database className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">{t("noKnowledgeBasesYet")}</p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
              {mayEdit
                ? "Create one to give your assistant access to documents from your collections."
                : "Nothing has been shared with you yet."}
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
              <KBCard key={kb.id} kb={kb} onDelete={mayEdit ? () => deleteKB(kb.id) : undefined} />
            ))}
          </div>
        )}
      </BasesCard>

      {/* Below the collections, because it is the thing they are fed from: a
          connector configured once and cloned into each base that needs it. */}
      <ReusableIntegrations targets={kbs} />

      <CreateKBDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={() => fetchKBs()} />
    </div>
  );
}

function KBCard({ kb, onDelete }: { kb: KnowledgeBase; onDelete?: () => void }) {
  const t = useTranslations("pages.kb");
  const meta = SCOPE_META[kb.scope];

  return (
    <div
      className={cn(
        "group border-border bg-card hover:border-foreground/30 hover:bg-accent relative flex flex-col rounded-xl border transition-colors",
      )}
    >
      {/* Whole-card link, stacked below the interactive controls and above
          nothing else.

          The z-indexes here are load-bearing and were wrong in both
          directions, so they are worth stating. Originally the link sat at
          `z-10` under content at `z-20`: every click hit the card body and the
          link was unreachable despite carrying the right `href`. Swapping them
          put the link over the delete button, whose `pointer-events-auto`
          could not help it from a lower layer.

          What works, verified with `elementFromPoint` rather than by reasoning
          about it: the content wrapper carries **no** z-index, so it creates no
          stacking context and the delete button's own `z-30` is measured
          against the link's `z-20` instead of being trapped beneath it. The
          wrapper stays `pointer-events-none` so clicks over dead space fall
          through to the link, and the button re-enables them for itself.

          A `z-index` on that wrapper - which is what it had - silently wins
          over any value a child sets, which is why the obvious fix of raising
          the button did nothing. */}
      <Link
        href={ROUTES.KB_DETAIL(kb.id)}
        className="focus-visible:ring-ring absolute inset-0 z-20 rounded-[inherit] focus-visible:ring-2 focus-visible:outline-none"
        aria-label={`Open ${kb.name}`}
      />

      <div className="pointer-events-none flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-2">
          <span className="bg-muted text-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
            <meta.icon className="h-4 w-4" />
          </span>

          <div className="flex items-center gap-1.5">
            {kb.is_default && (
              <Badge variant="outline" className="border-border text-muted-foreground font-normal">
                {t("default")}
              </Badge>
            )}
            {!kb.is_default && onDelete && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (
                    confirm(
                      `Delete "${kb.name}"? This will remove the knowledge base and all its documents.`,
                    )
                  ) {
                    onDelete();
                  }
                }}
                className="text-muted-foreground hover:bg-accent hover:text-destructive pointer-events-auto relative z-30 inline-flex h-8 w-8 items-center justify-center rounded-lg opacity-0 transition-colors group-hover:opacity-100 focus-visible:opacity-100"
                aria-label={t("deleteKnowledgeBase")}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
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
            <span className="truncate">{meta.label}</span>
          </span>
          <ArrowUpRight className="h-4 w-4 shrink-0" />
        </div>
      </div>
    </div>
  );
}
