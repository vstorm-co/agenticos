"use client";

import { useState, type RefObject } from "react";
import { useTranslations } from "next-intl";
import { Label, MarkdownEditor, MarkdownModeToggle, type MarkdownMode } from "@/components/ui";

export function PromptField({
  value,
  textareaRef,
  onChange,
  rows = 6,
  disabled = false,
}: {
  value: string;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  disabled?: boolean;
  onChange: (value: string) => void;
  /** The wizard's message step passes more - a prompt is often long. */
  rows?: number;
}) {
  const t = useTranslations("triggers");
  const [mode, setMode] = useState<MarkdownMode>("source");
  return (
    <div className="space-y-1.5">
      <MarkdownEditor
        id="trigger-prompt"
        textareaRef={textareaRef}
        disabled={disabled}
        toolbar={
          <>
            <Label htmlFor="trigger-prompt" className="flex-1">
              {t("prompt")}
            </Label>
            <MarkdownModeToggle mode={mode} onChange={setMode} />
          </>
        }
        label={t("prompt")}
        value={value}
        onChange={onChange}
        placeholder={t("promptPlaceholder")}
        rows={rows}
        describedBy="trigger-prompt-desc"
        mode={mode}
      />
      <p id="trigger-prompt-desc" className="text-muted-foreground text-xs leading-relaxed">
        {t("promptHelp")}
      </p>
    </div>
  );
}
