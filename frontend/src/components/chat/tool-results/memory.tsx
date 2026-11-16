"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { Brain, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { recordedMemoryStatement } from "@/lib/turn-extras";
import type { ToolCall } from "@/types";
import { GenericToolResult } from "./generic";

/** The tool's response remains authoritative, including refusals and disputed claims. */
export function MemoryToolResult({
  toolCall,
  resultText,
}: {
  toolCall: ToolCall;
  resultText: string;
}) {
  const t = useTranslations("chat.tools");
  const statement = recordedMemoryStatement(toolCall);
  const labels = useTranslations("pages.memory.browser");
  const kind = toolCall.args.kind;
  const kindLabel = kind === "fact" || kind === "preference" || kind === "decision" ? kind : "fact";
  return (
    <div className="bg-muted/30 max-w-2xl overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-medium">
          <Brain className="text-muted-foreground size-4" />
          {t("memoryResult")}
        </span>
        <Link
          href="/settings/memory"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          {t("manageMemory")}
          <ArrowUpRight className="size-3" />
        </Link>
      </div>
      <div className="space-y-2 px-4 py-3">
        {statement && <p className="text-sm break-words whitespace-pre-wrap">{statement}</p>}
        {statement ? (
          <div className="text-muted-foreground flex flex-wrap gap-2 text-xs">
            {toolLookupName(toolCall) === "remember" && (
              <span className="bg-muted rounded px-1.5 py-0.5">{labels(`kind.${kindLabel}`)}</span>
            )}
            <span>
              {toolLookupName(toolCall) === "correct_memory"
                ? t("memoryCorrectedResult")
                : t("memoryRecordedResult")}
            </span>
          </div>
        ) : (
          <GenericToolResult toolCall={{ ...toolCall, args: {} }} resultText={resultText} />
        )}
      </div>
    </div>
  );
}
