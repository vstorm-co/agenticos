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
    <Card className="peek-card group hover:border-foreground/20 relative h-full overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        className="flex h-full w-full flex-col rounded-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        {/* Not on a phone - see `SkillCard`. */}
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
        <span className="flex flex-1 flex-col gap-1.5 p-4 pt-3.5 pb-12">
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
          <AudienceChip visibility={file.visibility} groups={file.shared_groups} />
          <UsedBy agents={file.used_by} />
        </span>
      </button>
      {/* Beside the card's own controls rather than inside the button that opens
          it: giving it to an agent is the next step after writing one (#2075). It
          keeps the card's edge, and the bin that appears on hover sits beside it
          rather than holding a gap open when it does not. */}
      <div className="absolute right-4 bottom-3 flex items-center gap-1">
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
    </Card>
  );
}
