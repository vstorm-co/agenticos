"use client";

import { toolLookupName } from "@/lib/tool-identity";

import Link from "next/link";
import {
  ArrowUpRight,
  CheckCheck,
  FolderKanban,
  Table2,
  Bot,
  GitBranch,
  BookOpen,
  FileText,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { ToolCall } from "@/types";

interface PlatformObject {
  id: string;
  kind: "project" | "table" | "task" | "record" | "agent" | "workflow" | "skill" | "context";
  title: string | null;
  href: string;
  status?: string;
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value))
    : null;
}

function response(call: ToolCall): Record<string, unknown> | null {
  if (call.status !== "completed") return null;
  let value: unknown = call.result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch (error) {
      if (error instanceof SyntaxError) return null;
      throw error;
    }
  }
  return object(value);
}

/** MCP domain refusals arrive as tool output, rather than a transport exception. */
export function platformCallError(call: ToolCall): string | null {
  if (!toolLookupName(call).startsWith("agenticos_")) return null;
  if (typeof call.result === "string" && !/^\s*\{\s*"error"\s*:/.test(call.result)) return null;
  const envelope = object(response(call)?.error);
  return typeof envelope?.message === "string" ? envelope.message : null;
}

/** Successful platform writes only; error envelopes never become success cards. */
export function platformObjects(calls: ToolCall[]): PlatformObject[] {
  const found = new Map<string, PlatformObject>();
  const columns = new Map<string, string>();
  const supported = new Set([
    "agenticos_create_agent_draft",
    "agenticos_update_agent_draft",
    "agenticos_create_workflow_draft",
    "agenticos_update_workflow_draft",
    "agenticos_create_skill",
    "agenticos_update_skill",
    "agenticos_create_context_file",
    "agenticos_update_context_file",
    "agenticos_get_virtual_table",
    "agenticos_create_project",
    "agenticos_update_project",
    "agenticos_create_virtual_table",
    "agenticos_update_virtual_table_schema",
    "agenticos_create_task",
    "agenticos_update_task",
    "agenticos_add_virtual_table_record",
    "agenticos_update_virtual_table_record",
  ]);
  for (const call of calls) {
    if (!supported.has(toolLookupName(call))) continue;
    const data = response(call);
    if (!data || data.error) continue;
    if (typeof data.id === "string" && Array.isArray(data.columns)) {
      const primary = data.columns.map(object).find((column) => column?.type === "text");
      if (typeof primary?.id === "string") columns.set(data.id, primary.id);
    }
    const name = toolLookupName(call);
    const id = data.id;
    if (typeof id !== "string" || !/^[0-9a-f-]{36}$/i.test(id)) continue;
    let item: PlatformObject | null = null;
    const draft = object(data.draft_spec);
    if (["agenticos_create_agent_draft", "agenticos_update_agent_draft"].includes(name)) {
      item = {
        id,
        kind: "agent",
        title:
          typeof data.name === "string"
            ? data.name
            : typeof draft?.name === "string"
              ? draft.name
              : null,
        href: `/agents/${id}`,
      };
    } else if (
      ["agenticos_create_workflow_draft", "agenticos_update_workflow_draft"].includes(name)
    ) {
      item = {
        id,
        kind: "workflow",
        title: typeof data.name === "string" ? data.name : null,
        href: `/workflows/${id}`,
      };
    } else if (["agenticos_create_skill", "agenticos_update_skill"].includes(name)) {
      item = {
        id,
        kind: "skill",
        title: typeof data.name === "string" ? data.name : null,
        href: "/skills",
      };
    } else if (["agenticos_create_context_file", "agenticos_update_context_file"].includes(name)) {
      item = {
        id,
        kind: "context",
        title: typeof data.name === "string" ? data.name : null,
        href: "/context",
      };
    } else if (["agenticos_create_project", "agenticos_update_project"].includes(name)) {
      item = {
        id,
        kind: "project",
        title: typeof data.name === "string" ? data.name : null,
        href: `/projects/${id}`,
      };
    } else if (
      ["agenticos_create_virtual_table", "agenticos_update_virtual_table_schema"].includes(name)
    ) {
      item = {
        id,
        kind: "table",
        title: typeof data.name === "string" ? data.name : null,
        href: `/tables/${id}`,
      };
    } else if (
      ["agenticos_create_task", "agenticos_update_task"].includes(name) &&
      typeof data.table_id === "string"
    ) {
      item = {
        id,
        kind: "task",
        title: typeof data.title === "string" ? data.title : null,
        href: `/tables/${encodeURIComponent(data.table_id)}`,
        status: typeof data.status === "string" ? data.status : undefined,
      };
    } else if (
      ["agenticos_add_virtual_table_record", "agenticos_update_virtual_table_record"].includes(
        name,
      ) &&
      typeof data.table_id === "string"
    ) {
      const values = object(data.values);
      const primary = columns.get(data.table_id);
      const title = primary ? values?.[primary] : null;
      item = {
        id,
        kind: "record",
        title: typeof title === "string" ? title : null,
        href: `/tables/${encodeURIComponent(data.table_id)}`,
      };
    }
    if (item) found.set(`${item.kind}:${id}`, item);
  }
  return [...found.values()];
}

export function PlatformObjects({ calls }: { calls: ToolCall[] }) {
  const t = useTranslations("chat.platformObjects");
  const tasks = useTranslations("durableTasks");
  const items = platformObjects(calls);
  if (!items.length) return null;
  return (
    <div className="grid max-w-2xl gap-2 sm:grid-cols-2">
      {items.map((item) => {
        const icons = {
          project: FolderKanban,
          table: Table2,
          task: CheckCheck,
          record: CheckCheck,
          agent: Bot,
          workflow: GitBranch,
          skill: BookOpen,
          context: FileText,
        };
        const Icon = icons[item.kind];
        const knownStatus = [
          "planned",
          "in_progress",
          "waiting_for_user",
          "blocked",
          "done",
          "cancelled",
        ].includes(item.status ?? "");
        return (
          <Link
            key={`${item.kind}:${item.id}`}
            href={item.href}
            className="group border-foreground/10 bg-muted/20 hover:border-foreground/20 hover:bg-muted/40 focus-visible:ring-ring step-in flex min-w-0 items-start gap-3 rounded-xl border p-3 transition-colors focus-visible:ring-2 motion-reduce:animate-none"
          >
            <span className="bg-foreground/5 text-muted-foreground grid size-9 shrink-0 place-items-center rounded-lg">
              <Icon className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="text-muted-foreground block text-[11px]">{t(item.kind)}</span>
              <span className="text-foreground mt-0.5 block truncate text-sm font-medium">
                {item.title ?? t(item.kind)}
              </span>
              {knownStatus && (
                <span className="text-muted-foreground mt-1 block text-xs">
                  {tasks(`status.${item.status}`)}
                </span>
              )}
            </span>
            <ArrowUpRight
              className="text-muted-foreground mt-1 size-3.5 shrink-0 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 motion-reduce:transform-none"
              aria-hidden
            />
          </Link>
        );
      })}
    </div>
  );
}
