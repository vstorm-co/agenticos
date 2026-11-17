"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Input,
  Label,
  MarkdownEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { usePromptPreview } from "@/hooks/use-event-sources";
import { getErrorMessage } from "@/lib/api-error";
import { insertPromptField, promptFields } from "@/lib/routine-prompt-fields";
import type { EventSample } from "@/lib/event-sources-api";
import { LiveSample, PasteSample } from "./live-sample";

export function RoutinePrompt({
  value,
  onChange,
  mode,
  onModeChange,
  sourceId,
  agentId,
  triggerId,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  mode: "literal" | "template";
  onModeChange: (mode: "literal" | "template") => void;
  sourceId: string | null;
  agentId: string | null;
  triggerId?: string;
  disabled?: boolean;
}) {
  const t = useTranslations("eventSources");
  const triggerCopy = useTranslations("triggers");
  const errors = useTranslations("errors");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [sample, setSample] = useState<EventSample | null>(null);
  const [search, setSearch] = useState("");
  const preview = usePromptPreview(agentId ?? "");
  const change = (next: string) => {
    onChange(next);
    preview.reset();
  };
  const insert = (path: string) => {
    const next = insertPromptField(
      value,
      path,
      textarea.current?.selectionStart ?? value.length,
      textarea.current?.selectionEnd ?? value.length,
    );
    change(next.value);
    requestAnimationFrame(() => {
      textarea.current?.focus();
      textarea.current?.setSelectionRange(next.caret, next.caret);
    });
  };
  return (
    <div className="space-y-3">
      <Label htmlFor="routine-prompt-mode">{t("promptMode")}</Label>
      <Select
        value={mode}
        disabled={disabled}
        onValueChange={(next) => {
          onModeChange(next as "literal" | "template");
          preview.reset();
        }}
      >
        <SelectTrigger id="routine-prompt-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="literal">{t("literal")}</SelectItem>
          <SelectItem value="template">{t("template")}</SelectItem>
        </SelectContent>
      </Select>
      <MarkdownEditor
        id="trigger-prompt"
        textareaRef={textarea}
        label={triggerCopy("prompt")}
        value={value}
        onChange={change}
        rows={8}
        disabled={disabled}
      />
      {sourceId ? (
        <LiveSample
          key={sourceId}
          sourceId={sourceId}
          onSample={(next) => {
            setSample(next);
            preview.reset();
          }}
        />
      ) : (
        <PasteSample
          onSample={(next) => {
            setSample(next);
            preview.reset();
          }}
        />
      )}
      {mode === "template" && (
        <>
          <p className="text-muted-foreground text-xs">
            {t("templateHelp", { field: "{{issue.title}}", arrayField: "{{items[0].name}}" })}
          </p>
          {sample && (
            <div className="space-y-2">
              <Label htmlFor="prompt-field-search">{t("fields")}</Label>
              <Input
                id="prompt-field-search"
                placeholder={t("searchFields")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div
                className="max-h-56 overflow-auto rounded-md border"
                role="group"
                aria-label={t("fields")}
              >
                {promptFields(sample.body)
                  .filter((field) => field.path.toLowerCase().includes(search.toLowerCase()))
                  .map((field) => (
                    <button
                      key={field.path}
                      type="button"
                      disabled={disabled}
                      className="hover:bg-muted flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs"
                      style={{ paddingInlineStart: 12 + field.depth * 12 }}
                      onClick={() => insert(field.path)}
                    >
                      <code className="shrink-0">{`{{${field.path}}}`}</code>
                      <span className="text-muted-foreground truncate">
                        {JSON.stringify(field.value)}
                      </span>
                    </button>
                  ))}
              </div>
              <Button
                type="button"
                variant="outline"
                disabled={!agentId || preview.isPending || disabled}
                onClick={() =>
                  preview.mutate({
                    prompt: value,
                    payload: sample.body,
                    ...(sourceId ? { source_id: sourceId } : {}),
                    ...(triggerId ? { trigger_id: triggerId } : {}),
                  })
                }
              >
                {t("preview")}
              </Button>
            </div>
          )}
          {preview.error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(preview.error, errors)}
            </p>
          )}
          {preview.data && (
            <div className="space-y-2">
              <Label>{t("resolvedPrompt")}</Label>
              <pre className="bg-muted max-h-72 overflow-auto rounded-md p-3 text-sm whitespace-pre-wrap">
                {preview.data.resolved_prompt}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
