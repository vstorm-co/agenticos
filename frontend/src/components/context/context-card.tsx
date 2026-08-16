"use client";

import { FileText, Trash2 } from "lucide-react";

import { Badge, Button, Card, CardContent } from "@/components/ui";
import { formatBytes } from "@/lib/utils";
import type { ContextFileSummary } from "@/types/providers";
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
    <Card className="hover:border-foreground/20 h-full transition-colors">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 space-y-1.5 text-left">
          <span className="flex items-center gap-2">
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
          <span className="text-muted-foreground flex items-center gap-1 text-xs">
            <FileText className="h-3.5 w-3.5 shrink-0" />
            {t("sizeWithFormat", { format: file.format, size: formatBytes(file.size_bytes) })}
          </span>
        </button>
        {canEdit && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={tc("deleteNamed", { name: file.name })}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
