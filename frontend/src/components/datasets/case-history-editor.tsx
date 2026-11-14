"use client";

import { Bot, Plus, UserRound, X } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { DatasetChip } from "./dataset-chip";
import type { TurnDraft } from "./case-form";

interface CaseHistoryEditorProps {
  turns: TurnDraft[];
  onChange: (turns: TurnDraft[]) => void;
}

/** The turns before the input, oldest first, each a speaker and what they said. */
export function CaseHistoryEditor({ turns, onChange }: CaseHistoryEditorProps) {
  const t = useTranslations("datasets");
  const change = (index: number, patch: Partial<TurnDraft>) =>
    onChange(turns.map((turn, at) => (at === index ? { ...turn, ...patch } : turn)));
  const next: TurnDraft["role"] = turns.at(-1)?.role === "user" ? "assistant" : "user";

  return (
    <div className="space-y-2">
      {turns.map((turn, index) => (
        <div key={index} className="bg-muted/20 min-w-0 space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2">
            <Select
              value={turn.role}
              onValueChange={(role) => change(index, { role: role as TurnDraft["role"] })}
            >
              <SelectTrigger
                className="h-8 w-36 min-w-0"
                aria-label={t("turnRole", { number: index + 1 })}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user" textValue={t("role.user")}>
                  <DatasetChip tone="blue" icon={UserRound}>
                    {t("role.user")}
                  </DatasetChip>
                </SelectItem>
                <SelectItem value="assistant" textValue={t("role.assistant")}>
                  <DatasetChip tone="purple" icon={Bot}>
                    {t("role.assistant")}
                  </DatasetChip>
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("removeTurn", { number: index + 1 })}
              onClick={() => onChange(turns.filter((_, at) => at !== index))}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <Textarea
            className="min-h-20 w-full min-w-0"
            rows={2}
            placeholder={t("historyMessagePlaceholder")}
            value={turn.content}
            aria-label={t("turnContent", { number: index + 1 })}
            onChange={(event) => change(index, { content: event.target.value })}
          />
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange([...turns, { role: next, content: "" }])}
      >
        <Plus className="h-4 w-4" />
        {t("addTurn")}
      </Button>
    </div>
  );
}
