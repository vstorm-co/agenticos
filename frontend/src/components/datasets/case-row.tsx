"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import type { DatasetCase } from "@/types/datasets";

interface CaseRowProps {
  item: DatasetCase;
  onOpen: () => void;
  /** Absent when the case cannot be removed - an older version, or no edit access. */
  onRemove?: () => void;
}

/** One case in a version: its question, where it came from, and what it is checked on. */
export function CaseRow({ item, onOpen, onRemove }: CaseRowProps) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  return (
    <li className="group flex items-start gap-3 border-b py-3 last:border-b-0">
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 space-y-1.5 text-left">
        <span className="text-foreground line-clamp-2 block text-sm">{item.input}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{t(`source.${item.source}`)}</Badge>
          {item.history.length > 0 && (
            <Badge variant="outline">{t("turnsBefore", { count: item.history.length })}</Badge>
          )}
          {item.reference_answer !== null && <Badge variant="outline">{t("hasReference")}</Badge>}
          {item.counter_example !== null && (
            <Badge variant="outline">{t("hasCounterExample")}</Badge>
          )}
          {item.expected_tool_calls.length > 0 && (
            <Badge variant="outline">
              {t("expectedCalls", { count: item.expected_tool_calls.length })}
            </Badge>
          )}
          {item.tags.map((tag) => (
            <Badge key={tag} variant="outline" className="font-mono">
              {tag}
            </Badge>
          ))}
        </span>
      </button>
      {onRemove !== undefined && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={tc("delete")}
          onClick={onRemove}
          className="hover-reveal shrink-0"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </li>
  );
}
