"use client";

import Link from "next/link";
import { AlertTriangle, Check, Database, Layers, Loader2, Plus } from "lucide-react";

import {
  Badge,
  Pager,
  PICKER_PAGE_SIZE,
  SearchInput,
  useChosenFirst,
  useListControls,
} from "@/components/ui";
import { GroupsChip } from "@/components/sharing/audience-chip";
import { LoadingState } from "@/components/states";
import { agentBinding } from "@/lib/agent-collections";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { useOrgStore } from "@/stores/org-store";
import type { KnowledgeBase } from "@/types/knowledge-base";
import { useTranslations } from "next-intl";

interface CollectionPickerProps {
  collections: KnowledgeBase[];
  /** `spec.collection_ids`. */
  selectedIds: string[];
  onToggle: (collectionId: string) => void;
  disabled?: boolean;
  /**
   * Offer only what an agent in the current organization can bind
   * (`agentBinding`); publish refuses anything else. One already in
   * `selectedIds` stays listed, marked, so it can be removed. A workflow step
   * reads every collection the caller may read and leaves this off.
   */
  agentBindableOnly?: boolean;
}

/**
 * Which collections an agent may search, chosen on what is in them.
 *
 * This was a checkbox list of names, and a name is the one thing that does not
 * help here: every collection in an organization is called something plausible,
 * and the difference between the one with four hundred documents and the one
 * somebody created last week and never filled is invisible in it. Attaching the
 * empty one produces an agent that searches, finds nothing, and says so - which
 * reads as a broken agent rather than an empty collection.
 *
 * So each row carries its contents. Three facts, in the order they get used:
 * how many documents, how many chunks those became, and - only when they
 * disagree - how many never finished indexing. The last one is why the counts
 * are two numbers rather than one: a collection where a third of the uploads
 * died still reports them as documents, and nothing else in a listing would
 * ever mention it.
 *
 * The embedding model is shown because it is frozen at creation and cannot be
 * changed. Two collections built on different models are not interchangeable,
 * and this is the only surface that says so before one is attached.
 */
export function CollectionPicker({
  collections,
  selectedIds,
  onToggle,
  disabled,
  agentBindableOnly = false,
}: CollectionPickerProps) {
  const t = useTranslations("agents");
  // The organization every request is made as (`X-Organization-Id`), which
  // `ActiveOrgGuard` settles on every dashboard page.
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const chosen = new Set(selectedIds);
  const known = new Set(collections.map((collection) => collection.id));
  const refusal = (collection: KnowledgeBase) => {
    if (!agentBindableOnly || organizationId === null) return null;
    const binding = agentBinding(collection, organizationId);
    return binding === "bindable" ? null : binding;
  };
  const unbindable = (collection: KnowledgeBase) => refusal(collection) !== null;
  const offered = collections.filter(
    (collection) => !unbindable(collection) || chosen.has(collection.id),
  );
  // Named rather than dropped, for the same reason the skill gallery names them:
  // an id that quietly disappears from the form is still in the spec, and
  // publish is where it surfaces.
  const orphaned = selectedIds.filter((id) => !known.has(id));

  const ordered = useChosenFirst(offered, selectedIds);
  const list = useListControls({
    items: ordered,
    pageSize: PICKER_PAGE_SIZE,
    matches: (collection, query) =>
      collection.name.toLowerCase().includes(query) ||
      (collection.description ?? "").toLowerCase().includes(query),
  });

  // Until the organization is known nothing can be told apart, and a list that
  // drops rows a moment later invites a click on one publish would refuse.
  if (agentBindableOnly && organizationId === null) {
    return <LoadingState variant="skeleton-list" rows={3} />;
  }

  if (offered.length === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <Database className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-muted-foreground mt-2 text-sm">{t("organizationHasNoCollections")}</p>
        <Link
          href={ROUTES.RAG}
          className="mt-3 inline-flex items-center gap-1.5 text-sm underline underline-offset-4"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("createOne")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {offered.length > 8 && (
        <SearchInput
          value={list.query}
          onChange={list.setQuery}
          placeholder={t("searchCollections")}
        />
      )}

      <ul className="divide-border divide-y">
        {list.visible.map((collection) => {
          const isOn = chosen.has(collection.id);
          const refused = refusal(collection);
          const pending = collection.document_count - collection.indexed_count;
          return (
            <li key={collection.id}>
              <button
                type="button"
                role="checkbox"
                aria-checked={isOn}
                aria-label={collection.name}
                disabled={disabled}
                onClick={() => onToggle(collection.id)}
                className={cn(
                  "focus-visible:outline-ring flex min-h-12 w-full min-w-0 items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px]",
                  !disabled && "hover:bg-muted/60",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                    isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
                  )}
                >
                  {isOn && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium">{collection.name}</span>
                    {collection.is_default && <Badge variant="outline">{t("default")}</Badge>}
                    {refused && (
                      <Badge variant="outline">
                        {refused === "app" ? t("appWide") : t("otherOrganization")}
                      </Badge>
                    )}
                    <GroupsChip groups={collection.shared_groups} />
                  </span>

                  {refused && (
                    <span className="text-warning-ink mt-1 block text-sm">
                      {refused === "app"
                        ? t("appWideNotForAgents")
                        : t("otherOrganizationNotForAgents")}
                    </span>
                  )}

                  {collection.description && (
                    <span className="text-muted-foreground mt-1 block text-sm">
                      {collection.description}
                    </span>
                  )}

                  {/* The contents, as facts rather than a sentence: this row is
                    scanned against its neighbours, and a scanner reads columns. */}
                  <span className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span className="inline-flex items-center gap-1">
                      <Database className="h-3 w-3" />
                      {collection.document_count === 0
                        ? t("empty")
                        : t("documentCount", { count: collection.document_count })}
                    </span>
                    {collection.chunk_count > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <Layers className="h-3 w-3" />
                        {t("chunkCount", { count: collection.chunk_count })}
                      </span>
                    )}
                    {pending > 0 && (
                      // Deliberately not called "failed": this count is also what
                      // an upload in flight looks like, and the two are only
                      // distinguishable on the collection's own page.
                      <span className="text-foreground/70 inline-flex items-center gap-1">
                        {collection.indexed_count === 0 ? (
                          <Loader2 className="h-3 w-3" />
                        ) : (
                          <AlertTriangle className="h-3 w-3" />
                        )}
                        {t("notIndexedCount", { count: pending })}
                      </span>
                    )}
                    <span className="font-mono">{collection.embedding_model}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        counted={t("collectionCount", { count: list.total })}
      />

      {orphaned.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("orphanedCollections", { count: orphaned.length })}{" "}
          <span className="font-mono break-all">{orphaned.join(", ")}</span>
        </p>
      )}

      <p className="text-muted-foreground text-xs">
        {t.rich("collectionScopeHint", {
          link: (chunks) => (
            <Link href={ROUTES.RAG} className="underline underline-offset-4">
              {chunks}
            </Link>
          ),
        })}
      </p>
    </div>
  );
}
