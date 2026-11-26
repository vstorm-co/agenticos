"use client";

import {
  ChevronDown,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { AddToAgent } from "@/components/agents/add-to-agent";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
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
 * Every write control follows the server's effective access to this base.
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
  onEditSettings,
  onUploadWithSettings,
  onChooseFiles,
  onDelete,
}: {
  kb: KnowledgeBase;
  mayEdit: boolean;
  isLoading: boolean;
  isUploading: boolean;
  onRefresh: () => void;
  /** Opens the collection's own settings - how every later document is read. */
  onEditSettings: () => void;
  /** Opens the departures for the next uploads only; the collection is unchanged. */
  onUploadWithSettings: () => void;
  onChooseFiles: () => void;
  /** Asks for the deletion; the page owns the confirmation and the call. */
  onDelete: () => void;
}) {
  const t = useTranslations("pages.kb");
  return (
    <PageHeader
      className="mb-4"
      breadcrumbs={[{ label: t("knowledgeBases"), href: ROUTES.RAG }, { label: kb.name }]}
      title={kb.name}
      description={
        kb.description || <span className="font-mono text-xs">{kb.collection_name}</span>
      }
      secondaryActions={
        <>
          <AddToAgent resource={{ kind: "collection", id: kb.id }} name={kb.name} size="default" />
          <ShareResourceButton
            resourceType="collection"
            resourceId={kb.id}
            name={kb.name}
            canManage={mayEdit}
          />
          <Button variant="outline" onClick={onRefresh} disabled={isLoading}>
            <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
            {t("refresh")}
          </Button>
          {mayEdit && (
            <>
              <Button variant="outline" onClick={onEditSettings}>
                <SlidersHorizontal className="h-4 w-4" />
                {t("settings")}
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
                    <Button variant="outline" size="icon" aria-label={t("moreActions")}>
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
      actions={
        mayEdit && (
          // The per-upload departures sit on the action they modify, behind the
          // arrow: the collection's own settings are the header's Settings, and a
          // one-off is the exception, not the way settings are changed.
          <div className="flex items-center">
            <Button onClick={onChooseFiles} disabled={isUploading} className="rounded-r-none">
              {isUploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {isUploading ? t("uploading") : t("upload")}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="icon"
                  disabled={isUploading}
                  className="border-primary-foreground/20 rounded-l-none border-l"
                  aria-label={t("uploadOptions")}
                >
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={onUploadWithSettings}>
                  <SlidersHorizontal className="h-4 w-4" />
                  {t("uploadWithDifferentSettings")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )
      }
    />
  );
}
