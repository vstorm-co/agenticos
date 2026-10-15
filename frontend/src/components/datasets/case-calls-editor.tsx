"use client";

import { useId } from "react";
import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";
import { useCapabilityCatalog } from "@/hooks/use-agents";
import type { ArgDraft, CallDraft } from "./case-form";

/** What is typed in an empty row: a tool's name and an argument. Code, not copy. */
const TOOL_EXAMPLE = "search_kb";
const KEY_EXAMPLE = "query";
const VALUE_EXAMPLE = "refund";

interface CaseCallsEditorProps {
  calls: CallDraft[];
  onChange: (calls: CallDraft[]) => void;
  /** Tool names the dataset's cases already expect, suggested first. */
  knownTools?: string[];
}

/** One call's arguments, a name and a value per row. */
function ArgRows({
  call,
  number,
  onChange,
}: {
  call: CallDraft;
  number: number;
  onChange: (args: ArgDraft[]) => void;
}) {
  const t = useTranslations("datasets");
  const change = (index: number, patch: Partial<ArgDraft>) =>
    onChange(call.args.map((arg, at) => (at === index ? { ...arg, ...patch } : arg)));
  return (
    <div className="space-y-1.5 pl-4">
      {call.args.map((arg, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={arg.key}
            className="w-40 shrink-0 font-mono text-xs"
            aria-label={t("argKey", { number, arg: index + 1 })}
            placeholder={KEY_EXAMPLE}
            onChange={(event) => change(index, { key: event.target.value })}
          />
          <Input
            value={arg.value}
            className="font-mono text-xs"
            aria-label={t("argValue", { number, arg: index + 1 })}
            placeholder={VALUE_EXAMPLE}
            onChange={(event) => change(index, { value: event.target.value })}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("removeArg", { number, arg: index + 1 })}
            onClick={() => onChange(call.args.filter((_, at) => at !== index))}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => onChange([...call.args, { key: "", value: "" }])}
      >
        <Plus className="h-4 w-4" />
        {t("addArg")}
      </Button>
    </div>
  );
}

/**
 * The tools the agent should call, each with the arguments that must match.
 *
 * A tool's name is suggested from the ones this dataset's cases already expect
 * and from every tool an agent can be given, and is free text besides: an MCP
 * server's tools are named by the server, not the catalog. An argument's value
 * is plain text, or JSON when it reads as JSON - `5`, `true`, `["a"]`.
 */
export function CaseCallsEditor({ calls, onChange, knownTools = [] }: CaseCallsEditorProps) {
  const t = useTranslations("datasets");
  const listId = useId();
  const { capabilities } = useCapabilityCatalog();
  const tools = [
    ...new Set([
      ...knownTools,
      ...capabilities.flatMap((entry) => entry.tools.map((tool) => tool.id)),
    ]),
  ];
  const change = (index: number, patch: Partial<CallDraft>) =>
    onChange(calls.map((call, at) => (at === index ? { ...call, ...patch } : call)));

  return (
    <div className="space-y-3">
      <datalist id={listId}>
        {tools.map((tool) => (
          <option key={tool} value={tool} />
        ))}
      </datalist>
      {calls.map((call, index) => (
        <div key={index} className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Input
              list={listId}
              value={call.tool}
              className="w-56 font-mono text-xs"
              aria-label={t("callTool", { number: index + 1 })}
              placeholder={TOOL_EXAMPLE}
              onChange={(event) => change(index, { tool: event.target.value })}
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("removeCall", { number: index + 1 })}
              onClick={() => onChange(calls.filter((_, at) => at !== index))}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <ArgRows call={call} number={index + 1} onChange={(args) => change(index, { args })} />
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange([...calls, { tool: "", args: [] }])}
      >
        <Plus className="h-4 w-4" />
        {t("addCall")}
      </Button>
    </div>
  );
}
