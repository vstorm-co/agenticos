"use client";

import { FileIcon } from "@/components/files/file-icon";
import { displayName } from "./file-name";
import { BlankPeek, Card, DocPeek, TextPeek } from "@/components/ui";
import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { AudienceChip } from "@/components/sharing/audience-chip";
import type { ContextFileSummary } from "@/types/providers";

interface ContextCardProps {
  file: ContextFileSummary;
  onOpen: () => void;
}

/** Preview, usage and the next action, with concise metadata beside the action. */
export function ContextCard({ file, onOpen }: ContextCardProps) {
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
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
        <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1">
            <FileIcon name={displayName(file.name, file.format)} className="size-3.5" />
            {file.format.toUpperCase()}
          </span>
          <AudienceChip visibility={file.visibility} groups={file.shared_groups} />{" "}
        </div>
        <AddToAgent
          resource={{ kind: "context", id: file.id }}
          name={file.name}
          className="h-8 shrink-0"
        />
      </div>
    </Card>
  );
}
