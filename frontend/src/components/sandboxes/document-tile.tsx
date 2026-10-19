"use client";

import Image from "next/image";
import Link from "next/link";
import { Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { FileIcon } from "@/components/files";
import { Button, Card, DocPeek, TextPeek } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import type { FlatFile } from "@/lib/sandbox-workspaces-api";
import { cn, formatBytes, timeAgo } from "@/lib/utils";
import { documentName } from "@/lib/workspace-files";

/**
 * One file an agent is keeping, as the Documents page shows it.
 *
 * The shape every resource card has - a peek at the content on top, the name and
 * what it is under it - so a document reads as the same kind of thing as a skill
 * or a context file. Its name is the one the person gave it, not the path it is
 * filed under; the agent holding it is named with its face, and where it came
 * from - attached by a person or written by the agent - is a word beside it.
 * Who else can see it is the agent's sentence about its workspace, kept as the
 * tooltip on that line rather than repeated under every tile.
 */
export function DocumentTile({
  file,
  onOpen,
  onDownload,
}: {
  file: FlatFile;
  onOpen: () => void;
  onDownload: () => void;
}) {
  const t = useTranslations("sandboxes");
  const tc = useTranslations("common");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const name = documentName(file.path, file.from_upload);
  const thumbnail = resolveFileKind(file.path) === "image" ? file.thumbnail : null;
  const meta = [
    suffixOf(file.path).toUpperCase(),
    file.size === null ? null : formatBytes(file.size),
    file.modified_at === null ? null : timeAgo(file.modified_at, tTime, locale),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Card className="peek-card group hover:border-foreground/20 relative flex h-full flex-col overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        aria-label={tc("openNamed", { name })}
        className="flex flex-1 flex-col rounded-t-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        {/* Hidden on a phone, as a skill card's is: one tile per row, and a page
            of preview each made the list a scroll past pictures of text. */}
        <DocPeek
          className="h-28 max-sm:hidden"
          paperClassName={thumbnail !== null ? "p-0" : undefined}
        >
          {thumbnail !== null ? (
            <div className="bg-muted relative h-full w-full">
              <Image src={thumbnail} alt={name} fill className="object-cover" unoptimized />
            </div>
          ) : file.preview ? (
            <TextPeek
              source={file.preview}
              format={suffixOf(file.path) === "md" ? "markdown" : "plain"}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <FileIcon name={file.path} className="text-muted-foreground h-9 w-9" />
            </div>
          )}
        </DocPeek>
        <span className="flex flex-col gap-1 px-4 pt-3 pb-3">
          <span className="flex min-w-0 items-center gap-1.5">
            <FileIcon name={file.path} className="text-muted-foreground h-4 w-4 shrink-0" />
            <span title={file.path} className="text-foreground truncate text-sm font-medium">
              {name}
            </span>
          </span>
          <span className="text-muted-foreground text-xs">{meta}</span>
        </span>
      </button>
      <div className="border-border/60 flex items-center gap-2 border-t px-4 py-2">
        <AgentAvatar
          agentId={file.agent_id}
          slug={file.agent_slug}
          hasAvatar={file.agent_has_avatar}
          size="sm"
          className="h-5 w-5"
        />
        <Link
          href={ROUTES.DOCUMENT_FOLDER(file.workspace_id)}
          title={file.access_label}
          className="text-muted-foreground hover:text-foreground min-w-0 truncate text-xs"
        >
          {file.agent_name}
        </Link>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
            file.from_upload
              ? "bg-accent text-foreground"
              : "bg-foreground/[0.04] text-muted-foreground",
          )}
        >
          {file.from_upload ? t("workspaces.fromMe") : t("workspaces.fromTheAgent")}
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label={tc("downloadNamed", { name })}
          onClick={onDownload}
          className="text-muted-foreground ml-auto h-7 w-7 shrink-0"
        >
          <Download className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}
