"use client";

import { useRef, useState } from "react";

import { Button, MarkdownEditor } from "@/components/ui";
import type { ExposureVariable } from "@/types/exposures";
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
 *
 * The prose may name placeholders the platform fills in when a run starts -
 * `{channel_name}`, `{member_list}`. They are listed under the box and inserted
 * at the cursor by clicking one, because the alternative is remembering an exact
 * spelling that fails silently: an unknown brace is left as written, on purpose,
 * so a prompt quoting JSON still works.
 */
export function ExposurePrompt({
  botName,
  value,
  variables,
  disabled,
  onSave,
}: {
  botName: string;
  value: string | null;
  /** Placeholders this platform can fill in, resolved server-side. */
  variables: ExposureVariable[];
  disabled: boolean;
  onSave: (prompt: string | null) => void;
}) {
  const t = useTranslations("agents");
  const [draft, setDraft] = useState(value ?? "");
  const box = useRef<HTMLTextAreaElement>(null);
  const changed = draft.trim() !== (value ?? "").trim();

  /** Put a placeholder where the caret is, rather than at the end. */
  function insert(name: string) {
    const field = box.current;
    const at = field ? field.selectionStart : draft.length;
    setDraft(`${draft.slice(0, at)}{${name}}${draft.slice(at)}`);
    field?.focus();
  }

  return (
    <div className="space-y-2">
      {/* The same editor the agent's own Instructions use, for the same
          reason: this is Markdown the model reads as structure, and three rows
          of it is a keyhole onto a prompt somebody is composing. */}
      <MarkdownEditor
        textareaRef={box}
        value={draft}
        onChange={setDraft}
        label={t("channelPromptOn", { bot: botName })}
        placeholder={t("channelPromptPlaceholder")}
        rows={10}
        disabled={disabled}
      />
      {variables.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-muted-foreground text-xs">{t("channelPromptVariables")}</span>
          {variables.map((variable) => (
            <Button
              key={variable.name}
              type="button"
              size="sm"
              variant="outline"
              className="h-6 px-2 font-mono text-xs"
              disabled={disabled}
              title={variable.description}
              onClick={() => insert(variable.name)}
            >
              {`{${variable.name}}`}
            </Button>
          ))}
        </div>
      )}
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
