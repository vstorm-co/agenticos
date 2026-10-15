"use client";

import { Plus, X } from "lucide-react";
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
        <div key={index} className="flex items-start gap-2">
          <Select
            value={turn.role}
            onValueChange={(role) => change(index, { role: role as TurnDraft["role"] })}
          >
            <SelectTrigger
              className="w-32 shrink-0"
              aria-label={t("turnRole", { number: index + 1 })}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="user">{t("role.user")}</SelectItem>
              <SelectItem value="assistant">{t("role.assistant")}</SelectItem>
            </SelectContent>
          </Select>
          <Textarea
            rows={2}
            value={turn.content}
            aria-label={t("turnContent", { number: index + 1 })}
            onChange={(event) => change(index, { content: event.target.value })}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("removeTurn", { number: index + 1 })}
            onClick={() => onChange(turns.filter((_, at) => at !== index))}
          >
            <X className="h-4 w-4" />
          </Button>
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
