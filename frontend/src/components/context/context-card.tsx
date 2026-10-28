"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { FileIcon } from "@/components/files/file-icon";
import { displayName } from "./file-name";
import { BlankPeek, Button, Card, DocPeek, TextPeek } from "@/components/ui";
import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { AudienceChip } from "@/components/sharing/audience-chip";
import type { ContextFileSummary } from "@/types/providers";

interface ContextCardProps {
  file: ContextFileSummary;
  canEdit: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

/** Preview, agent usage and next action stay visible; taxonomy opens on demand. */
export function ContextCard({ file, canEdit, onOpen, onDelete }: ContextCardProps) {
  const tc = useTranslations("common");
  return (
    <Card className="peek-card group hover:border-foreground/20 flex flex-col overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-1 flex-col rounded-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        <DocPeek className="h-32 max-sm:hidden">
          {file.excerpt ? (
            <TextPeek
              source={file.excerpt}
              format={file.format === "md" || file.format === "markdown" ? "markdown" : "plain"}
            />
          ) : (
            <BlankPeek />
          )}
        </DocPeek>
        <span className="flex w-full flex-1 flex-col gap-1.5 p-4">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              className="text-foreground max-w-full truncate text-base font-semibold"
              title={file.name}
            >
              {file.name}
            </span>
          </span>
          <span className="text-foreground/85 line-clamp-2 min-h-10 text-sm leading-relaxed">
            {file.description}
          </span>
        </span>
      </button>
      <UsedBy agents={file.used_by} className="text-foreground/85 mx-4 mb-3 gap-2" />
      <div className="flex items-start justify-between gap-2 border-t px-3 py-2">
        <details className="text-muted-foreground min-w-0 flex-1 text-xs">
          <summary className="hover:text-foreground touch:min-h-11 cursor-pointer py-2 focus-visible:outline-offset-[-2px]">
            {tc("details")}
          </summary>
          <div className="space-y-2 pt-2 pb-1">
            <span className="flex items-center gap-1">
              <FileIcon name={displayName(file.name, file.format)} className="size-3.5" />
              {file.format.toUpperCase()}
            </span>
            <AudienceChip visibility={file.visibility} groups={file.shared_groups} />
            {canEdit && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={tc("deleteNamed", { name: file.name })}
                onClick={onDelete}
                className="h-8 w-8"
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            )}
          </div>
        </details>
        <AddToAgent
          resource={{ kind: "context", id: file.id }}
          name={file.name}
          className="h-8 shrink-0"
        />
      </div>
    </Card>
  );
}
