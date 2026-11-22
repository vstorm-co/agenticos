"use client";

import { BlankPeek, ResourceCard, DocPeek, TextPeek } from "@/components/ui";
import { RESOURCE_CARD_TRIGGER } from "@/components/ui/resource-card";
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
    <ResourceCard className="peek-card group isolate overflow-hidden p-0">
      <button
        type="button"
        data-press-feedback="quiet"
        onClick={onOpen}
        className={RESOURCE_CARD_TRIGGER}
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
        <span className="flex w-full flex-1 flex-col gap-1.5 p-5">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              className="text-foreground max-w-full truncate text-base font-semibold"
              title={file.name}
            >
              {file.name}
            </span>
          </span>
          <span className="text-foreground/85 line-clamp-3 min-h-16 text-sm leading-relaxed">
            {file.description}
          </span>
        </span>
      </button>
      <UsedBy agents={file.used_by} className="text-foreground/85 mx-5 mb-4 gap-2" />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4">
        <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <AudienceChip visibility={file.visibility} groups={file.shared_groups} />{" "}
        </div>
        <AddToAgent
          resource={{ kind: "context", id: file.id }}
          name={file.name}
          className="relative z-10 ml-auto h-8 shrink-0"
        />
      </div>
    </ResourceCard>
  );
}
