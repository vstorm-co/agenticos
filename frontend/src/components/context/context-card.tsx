"use client";

import { FileText, Trash2 } from "lucide-react";

import { BlankPeek, Button, Card, DocPeek, TextPeek } from "@/components/ui";
import type { ContextFileSummary } from "@/types/providers";
import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { AudienceChip } from "@/components/sharing/audience-chip";
import { useTranslations } from "next-intl";

interface ContextCardProps {
  file: ContextFileSummary;
  /** A viewer opens files to read them; only an editor gets the delete. */
  canEdit: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

/** Shared content and its users; each agent's Context binding owns its usage policy. */
export function ContextCard({ file, canEdit, onOpen, onDelete }: ContextCardProps) {
  const tc = useTranslations("common");
  return (
    <Card className="peek-card group hover:border-foreground/20 relative flex h-full flex-col overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-1 flex-col rounded-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        <span className="flex flex-1 flex-col gap-1.5 p-4">
          <span className="flex items-center gap-2 pr-8">
            <span className="text-foreground truncate text-sm font-semibold">{file.name}</span>
          </span>
          <span className="text-muted-foreground line-clamp-2 min-h-10 text-sm">
            {file.description}
          </span>
          <span className="text-muted-foreground mt-auto flex items-center gap-1 pt-1 text-xs">
            <FileText className="h-3.5 w-3.5 shrink-0" />
            {file.format.toUpperCase()}
          </span>
        </span>
      </button>
      <details className="group/details border-t">
        <summary className="text-muted-foreground hover:text-foreground touch:min-h-11 cursor-pointer px-4 py-2 text-xs focus-visible:outline-offset-[-2px]">
          {tc("details")}
        </summary>
        <div className="space-y-3 px-4 pb-4">
          <DocPeek className="h-28">
            {file.excerpt ? (
              <TextPeek
                source={file.excerpt}
                format={file.format === "md" || file.format === "markdown" ? "markdown" : "plain"}
              />
            ) : (
              <BlankPeek />
            )}
          </DocPeek>
          <AudienceChip visibility={file.visibility} groups={file.shared_groups} />
          <UsedBy agents={file.used_by} />
        </div>
        <div className="flex items-center justify-end gap-1 border-t px-3 py-2">
          {canEdit && (
            // Outside the open button - a button cannot hold another - and quiet until
            // the card is pointed at, so a grid of cards is not a column of bins.
            <Button
              variant="ghost"
              size="icon"
              aria-label={tc("deleteNamed", { name: file.name })}
              onClick={onDelete}
              className="hover-reveal h-8 w-8"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
          <AddToAgent
            resource={{ kind: "context", id: file.id }}
            name={file.name}
            className="h-8 text-xs"
          />
        </div>
      </details>
    </Card>
  );
}
