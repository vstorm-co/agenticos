"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { PromptField } from "@/components/triggers/prompt-field";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useEventSource, usePromptPreview } from "@/hooks/use-event-sources";
import { getErrorMessage } from "@/lib/api-error";
import type { EventSample } from "@/lib/event-sources-api";
import { insertPromptField, promptFields } from "@/lib/routine-prompt-fields";
import type { RoutinePromptMode } from "@/types/triggers";
import { LiveSample, PasteSample } from "./live-sample";

function PayloadFields({
  sample,
  onInsert,
  disabled,
}: {
  sample: EventSample;
  onInsert: (path: string) => void;
  disabled: boolean;
}) {
  const t = useTranslations("eventSources");
  const common = useTranslations("common");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(50);
  const fields = useMemo(() => promptFields(sample.body), [sample]);
  const query = search.toLowerCase();
  const matches = query ? fields.filter(({ path }) => path.toLowerCase().includes(query)) : fields;
  return (
    <div className="space-y-2">
      <Label htmlFor="prompt-field-search">{t("fields")}</Label>
      <Input
        id="prompt-field-search"
        placeholder={t("searchFields")}
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setLimit(50);
        }}
      />
      <div
        className="max-h-56 overflow-auto rounded-md border"
        role="group"
        aria-label={t("fields")}
      >
        {matches.slice(0, limit).map(({ path, depth, value }) => (
          <button
            key={path}
            type="button"
            disabled={disabled}
            className="hover:bg-muted flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs"
            style={{ paddingInlineStart: 12 + depth * 12 }}
            onClick={() => onInsert(path)}
          >
            <code className="shrink-0">{`{{${path}}}`}</code>
            <span className="text-muted-foreground truncate">
              {Array.isArray(value)
                ? "[…]"
                : value !== null && typeof value === "object"
                  ? "{…}"
                  : JSON.stringify(value)}
            </span>
          </button>
        ))}
        {matches.length > limit && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setLimit(limit + 50)}>
            {common("showMore")}
          </Button>
        )}
      </div>
    </div>
  );
}

export function RoutinePrompt({
  value,
  onChange,
  mode,
  onModeChange,
  sourceId,
  agentId,
  triggerId,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  mode: RoutinePromptMode;
  onModeChange: (mode: RoutinePromptMode) => void;
  sourceId: string | null;
  agentId: string | null;
  triggerId?: string;
  disabled?: boolean;
}) {
  const t = useTranslations("eventSources");
  const errors = useTranslations("errors");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [selection, setSelection] = useState<{ sample: EventSample; live: boolean } | null>(null);
  const useExample = (sample: EventSample) => setSelection({ sample, live: false });
  const source = useEventSource(sourceId);
  const canUseSource = !source.error && source.data?.can_use;
  const sample = selection && (!selection.live || canUseSource) ? selection.sample : null;
  const canPreview = agentId && (!sourceId || canUseSource);
  const preview = usePromptPreview(agentId ?? "");
  const currentPreview =
    preview.variables?.prompt === value && preview.variables.payload === sample?.body;
  const insert = (path: string) => {
    const next = insertPromptField(
      value,
      path,
      textarea.current?.selectionStart ?? value.length,
      textarea.current?.selectionEnd ?? value.length,
    );
    onChange(next.value);
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
        onValueChange={(next: RoutinePromptMode) => onModeChange(next)}
      >
        <SelectTrigger id="routine-prompt-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="literal">{t("literal")}</SelectItem>
          <SelectItem value="template">{t("template")}</SelectItem>
        </SelectContent>
      </Select>
      <PromptField
        value={value}
        onChange={onChange}
        textareaRef={textarea}
        rows={8}
        disabled={disabled}
      />
      {mode === "template" && (
        <p className="text-muted-foreground text-xs">
          {t("templateHelp", { field: "{{issue.title}}", arrayField: "{{items[0].name}}" })}
        </p>
      )}
      {sourceId ? (
        <LiveSample
          sourceId={sourceId}
          onSample={
            mode === "template"
              ? (caught) => setSelection({ sample: caught, live: true })
              : undefined
          }
          onPaste={mode === "template" ? useExample : undefined}
        />
      ) : (
        mode === "template" && <PasteSample onSample={useExample} />
      )}
      {mode === "template" && sample && (
        <>
          <PayloadFields sample={sample} onInsert={insert} disabled={disabled} />
          {canPreview && (
            <Button
              type="button"
              variant="outline"
              disabled={!value.trim() || preview.isPending || disabled}
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
          )}
          {canPreview && currentPreview && preview.error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(preview.error, errors)}
            </p>
          )}
          {canPreview && currentPreview && preview.data && (
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
