"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { ArrowDownLeft, ArrowUpRight, FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import type { WikiFlowNode } from "@/lib/wiki-flow";

export function WikiNode({ data, selected }: NodeProps<WikiFlowNode>) {
  const t = useTranslations("wikiGraph");
  return (
    <div
      className="bg-card text-card-foreground relative h-28 w-[236px] overflow-hidden rounded-2xl border shadow-md transition-[box-shadow,opacity]"
      style={{
        borderColor: selected
          ? data.colour
          : // i18n-exempt: CSS colour and shadow expressions, never user-facing text.
            `color-mix(in srgb, ${data.colour} 25%, var(--color-border))`,
        boxShadow: selected
          ? // i18n-exempt: CSS colour and shadow expressions, never user-facing text.
            `0 0 0 3px color-mix(in srgb, ${data.colour} 18%, transparent), 0 12px 32px -12px ${data.colour}55`
          : undefined,
      }}
    >
      <div className="absolute inset-y-0 left-0 w-1" style={{ background: data.colour }} />
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="!border-background !size-2 !border-2"
        style={{ background: data.colour }}
      />
      <div className="flex items-start gap-3 px-4 pt-3">
        <span
          className="mt-0.5 rounded-lg p-2"
          style={{
            // i18n-exempt: CSS colour and shadow expressions, never user-facing text.
            background: `color-mix(in srgb, ${data.colour} 12%, transparent)`,
            color: data.colour,
          }}
        >
          <FileText className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p
            className="truncate text-[10px] font-medium tracking-wide uppercase"
            style={{ color: data.colour }}
          >
            {data.group}
          </p>
          <p className="mt-1 line-clamp-2 text-[13px] leading-4 font-semibold">{data.page.title}</p>
        </div>
      </div>
      <div className="text-muted-foreground absolute inset-x-4 bottom-2 flex items-center justify-between text-[10px]">
        <span className="max-w-32 truncate">{data.page.path.split("/").at(-1)}</span>
        <span className="flex items-center gap-2">
          <span title={t("backlinks")} className="flex items-center gap-0.5">
            <ArrowDownLeft className="size-3" aria-hidden />
            {data.incoming}
          </span>
          <span title={t("outgoing")} className="flex items-center gap-0.5">
            <ArrowUpRight className="size-3" aria-hidden />
            {data.outgoing}
          </span>
        </span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="!border-background !size-2 !border-2"
        style={{ background: data.colour }}
      />
    </div>
  );
}
