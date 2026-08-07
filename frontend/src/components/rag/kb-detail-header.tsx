"use client";

import {
  Loader2,
  MoreHorizontal,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { KnowledgeBase } from "@/types";

/**
 * A collection's name, what it is, and everything that can be done to it.
 *
 * Every write control is drawn only for a caller holding `collections:edit`.
 * That is presentation and never enforcement - the routes behind these buttons
 * resolve access per row on the server - but offering a Viewer an action that
 * can only refuse is worse than not offering it.
 */
export function KBDetailHeader({
  kb,
  mayEdit,
  isLoading,
  isUploading,
  onRefresh,
  onEditParseOptions,
  onChooseFiles,
  onDelete,
}: {
  kb: KnowledgeBase;
  mayEdit: boolean;
  isLoading: boolean;
  isUploading: boolean;
  onRefresh: () => void;
  onEditParseOptions: () => void;
  onChooseFiles: () => void;
  /** Asks for the deletion; the page owns the confirmation and the call. */
  onDelete: () => void;
}) {
  const t = useTranslations("pages.kb");
  return (
    <PageHeader
      breadcrumbs={[{ label: t("knowledgeBases"), href: ROUTES.RAG }, { label: kb.name }]}
      title={kb.name}
      description={
        kb.description || <span className="font-mono text-xs">{kb.collection_name}</span>
      }
      actions={
        <>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={isLoading}>
            <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
            {t("refresh")}
          </Button>
          {mayEdit && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onEditParseOptions}
                disabled={isUploading}
              >
                <SlidersHorizontal className="h-4 w-4" />
                {t("parseOptions")}
              </Button>
              <Button size="sm" onClick={onChooseFiles} disabled={isUploading}>
                {isUploading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                {isUploading ? t("uploading") : t("upload")}
              </Button>
              {/* Behind a menu, not beside Refresh: destroying the collection
                  and everything in it is not a same-weight sibling of
                  re-reading it. It lives here rather than on the card in the
                  list because this is the page that says what is inside.

                  Not drawn at all for the default collection, which
                  `KnowledgeBaseService.delete` refuses outright - offering it
                  would be offering an action that can only answer 400. The
                  card in the list hid it for the same reason. */}
              {!kb.is_default && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-8 px-0"
                      aria-label={t("moreActions")}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onSelect={onDelete}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t("deleteKnowledgeBase")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </>
          )}
        </>
      }
    />
  );
}
