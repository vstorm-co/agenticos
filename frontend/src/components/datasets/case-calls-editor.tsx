"use client";

import { useId } from "react";
import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";
import { useCapabilityCatalog } from "@/hooks/use-agents";
import type { CallDraft } from "./case-form";

/** What is typed in an empty row: a tool's name and its arguments. Code, not copy. */
const TOOL_EXAMPLE = "search_kb";
const ARGS_EXAMPLE = '{"query": "refund"}';

interface CaseCallsEditorProps {
  calls: CallDraft[];
  onChange: (calls: CallDraft[]) => void;
}

/**
 * The tools the agent should call, each with the arguments that must match.
 *
 * A tool's name is suggested from every tool an agent can be given, and is free
 * text besides: an MCP server's tools are named by the server, not the catalog.
 */
export function CaseCallsEditor({ calls, onChange }: CaseCallsEditorProps) {
  const t = useTranslations("datasets");
  const listId = useId();
  const { capabilities } = useCapabilityCatalog();
  const tools = [...new Set(capabilities.flatMap((entry) => entry.tools.map((tool) => tool.id)))];
  const change = (index: number, patch: Partial<CallDraft>) =>
    onChange(calls.map((call, at) => (at === index ? { ...call, ...patch } : call)));

  return (
    <div className="space-y-2">
      <datalist id={listId}>
        {tools.map((tool) => (
          <option key={tool} value={tool} />
        ))}
      </datalist>
      {calls.map((call, index) => (
        <div key={index} className="flex items-start gap-2">
          <Input
            list={listId}
            value={call.tool}
            className="w-56 shrink-0 font-mono text-xs"
            aria-label={t("callTool", { number: index + 1 })}
            placeholder={TOOL_EXAMPLE}
            onChange={(event) => change(index, { tool: event.target.value })}
          />
          <Input
            value={call.args}
            className="font-mono text-xs"
            aria-label={t("callArgs", { number: index + 1 })}
            placeholder={ARGS_EXAMPLE}
            onChange={(event) => change(index, { args: event.target.value })}
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
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange([...calls, { tool: "", args: "" }])}
      >
        <Plus className="h-4 w-4" />
        {t("addCall")}
      </Button>
    </div>
  );
}
