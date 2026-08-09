"use client";

import { useState } from "react";

import { Button, Textarea } from "@/components/ui";
import { useTranslations } from "next-intl";

/**
 * What to add to the agent's instructions on one binding.
 *
 * The same published agent answers in a dashboard, on a website widget and in a
 * Mattermost channel, and those want different things of it: how to lay a
 * message out, whether headings will render, how to give a link, how long an
 * answer should be. None of that is a different agent, and editing the spec to
 * suit one surface changes it on every other.
 *
 * Saved on a button rather than on every keystroke: this is prose somebody is
 * composing, and a mutation per character would republish the agent's behaviour
 * mid-sentence.
 */
export function ExposurePrompt({
  botName,
  value,
  disabled,
  onSave,
}: {
  botName: string;
  value: string | null;
  disabled: boolean;
  onSave: (prompt: string | null) => void;
}) {
  const t = useTranslations("agents");
  const [draft, setDraft] = useState(value ?? "");
  const changed = draft.trim() !== (value ?? "").trim();

  return (
    <div className="space-y-2">
      <Textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={t("channelPromptPlaceholder")}
        aria-label={t("channelPromptOn", { bot: botName })}
        rows={3}
        maxLength={4000}
      />
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-xs">{t("channelPromptHint")}</p>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || !changed}
          // Empty means "nothing extra here", which is a null rather than a
          // blank string: the run appends what it finds, and an empty line
          // appended to every prompt is still an edit to every prompt.
          onClick={() => onSave(draft.trim() === "" ? null : draft.trim())}
        >
          {t("save4")}
        </Button>
      </div>
    </div>
  );
}
