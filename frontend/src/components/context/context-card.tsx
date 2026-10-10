"use client";

import { FileText, Trash2 } from "lucide-react";

import { Badge, BlankPeek, Button, Card, DocPeek, TextPeek } from "@/components/ui";
import { cn, formatBytes } from "@/lib/utils";
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

/**
 * One context file in the list.
 *
 * The mode badge is the one thing that is never implicit: `inject` and `link`
 * behave differently enough - one spends tokens every run, the other is read on
 * demand - that a reader must not have to open the file to tell which it is. A
 * `disabled` badge marks a file agents are currently skipping.
 */
export function ContextCard({ file, canEdit, onOpen, onDelete }: ContextCardProps) {
  const t = useTranslations("context");
  const tc = useTranslations("common");
  return (
    <Card className="peek-card group hover:border-foreground/20 relative h-full overflow-hidden">
      <button type="button" onClick={onOpen} className="flex h-full w-full flex-col text-left">
        <DocPeek className="h-32">
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
            <span className="text-foreground truncate font-mono text-sm font-medium">
              {file.name}
            </span>
            <Badge variant={file.mode === "inject" ? "secondary" : "outline"}>
              {t(file.mode === "inject" ? "modeInject" : "modeLink")}
            </Badge>
            {!file.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
          </span>
          {file.description !== null && (
            <span className="text-muted-foreground line-clamp-2 block text-sm">
              {file.description}
            </span>
          )}
          <span className="text-muted-foreground mt-auto flex items-center gap-1 pt-1 text-xs">
            <FileText className="h-3.5 w-3.5 shrink-0" />
            {t("sizeWithFormat", { format: file.format, size: formatBytes(file.size_bytes) })}
          </span>
          <AudienceChip visibility={file.visibility} groups={file.shared_groups} />
          <UsedBy agents={file.used_by} />
        </span>
      </button>
      {/* Beside the card's own controls rather than inside the button that opens
          it: giving it to an agent is the next step after writing one (#2075). */}
      <AddToAgent
        resource={{ kind: "context", id: file.id }}
        name={file.name}
        className={cn("absolute bottom-2 h-8 text-xs", canEdit ? "right-12" : "right-2")}
      />
      {canEdit && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={tc("deleteNamed", { name: file.name })}
          onClick={onDelete}
          className="hover-reveal absolute right-2 bottom-2"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </Card>
  );
}
