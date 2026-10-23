"use client";

import Link from "next/link";
import { Archive, ArchiveRestore, Globe, MoreHorizontal, Trash2, Users } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ArtifactThumbnail } from "@/components/artifacts/artifact-thumbnail";
import { LiveBadge } from "@/components/artifacts/live-badge";
import { groupsLabel } from "@/components/sharing/audience-chip";
import {
  Badge,
  Card,
  DocPeek,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { Artifact } from "@/types/artifact";

export interface ArtifactCardActions {
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}

/**
 * One artifact in the list: the page itself, live, on top.
 *
 * Earlier versions stack behind it, one sheet per version kept past the first,
 * so a report that has been through seven drafts looks it. Who can reach it is
 * never implicit: a badge for an organization-wide page and another for one with
 * a public link, because "who else is reading this" is the first thing to know
 * about a report before forwarding it. An archived page serves nothing, so it
 * says so instead of drawing a page that would not load.
 *
 * The whole card is the link to the page and the menu sits outside it, for the
 * reason `AgentCard` gives. `actions` is passed only to a member who may change
 * pages; without it there is no menu.
 */
export function ArtifactCard({
  artifact,
  actions,
  busy,
}: {
  artifact: Artifact;
  actions?: ArtifactCardActions;
  busy?: boolean;
}) {
  const t = useTranslations("artifacts");
  const ta = useTranslations("agents");
  const tc = useTranslations("common");
  const format = useFormatter();
  const tAudience = useTranslations("audience");
  const groups = artifact.shared_groups ?? [];
  const version = artifact.current_version?.number ?? 0;
  const archived = artifact.archived_at !== null;
  return (
    <Card
      className={cn(
        "peek-card group hover:border-foreground/20 relative flex h-full flex-col overflow-hidden",
        busy && "pointer-events-none opacity-50",
      )}
    >
      <Link
        href={ROUTES.ARTIFACT_DETAIL(artifact.id)}
        className="focus-visible:ring-ring absolute inset-0 rounded-2xl outline-none focus-visible:ring-2"
        aria-label={tc("openNamed", { name: artifact.title })}
      />
      <DocPeek
        sheets={version - 1}
        badge={version > 0 ? t("versionBadge", { version }) : undefined}
        className="pointer-events-none h-40"
        paperClassName="p-0"
      >
        {artifact.current_version !== null && !archived && (
          <ArtifactThumbnail artifactId={artifact.id} title={artifact.title} />
        )}
      </DocPeek>
      <div className="pointer-events-none relative flex flex-1 flex-col gap-1.5 p-4 pt-3.5">
        <span className="text-foreground truncate text-sm font-medium">{artifact.title}</span>
        <span className="text-muted-foreground block truncate font-mono text-xs">
          {artifact.name}
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          {archived && (
            <Badge variant="outline" className="gap-1">
              <Archive className="h-3 w-3" />
              {t("archivedBadge")}
            </Badge>
          )}
          {artifact.environment_name !== null && (
            <Badge variant="outline" title={t("environmentBadge")} className="pointer-events-auto">
              {artifact.environment_name}
            </Badge>
          )}
          {artifact.visibility === "org" && <Badge variant="secondary">{t("sharedOrg")}</Badge>}
          {/* Its departments, as every other resource's card names them. */}
          {groups.length > 0 && (
            <Badge variant="secondary" className="gap-1">
              <Users className="h-3 w-3" aria-hidden />
              {groupsLabel(groups, tAudience)}
            </Badge>
          )}
          {/* An archived page serves nothing, live data included. */}
          {artifact.live && !archived && <LiveBadge />}
          {artifact.public_url !== null && (
            <Badge variant="outline" className="gap-1">
              <Globe className="h-3 w-3" />
              {t("publicBadge")}
            </Badge>
          )}
        </span>
        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <span className="text-muted-foreground min-w-0 truncate text-xs">
            {t("publishedVersion", {
              version,
              when: format.dateTime(new Date(artifact.published_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </span>
          {actions && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={ta("moreActionsFor", { name: artifact.title })}
                  className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring pointer-events-auto -my-1.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {archived ? (
                  <DropdownMenuItem onSelect={actions.onRestore}>
                    <ArchiveRestore className="h-4 w-4" />
                    {t("unarchive")}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onSelect={actions.onArchive}>
                    <Archive className="h-4 w-4" />
                    {t("archive")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={actions.onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  {ta("deletePermanently")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </Card>
  );
}
