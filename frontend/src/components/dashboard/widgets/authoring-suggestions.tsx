"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { useWaitingSuggestions } from "@/hooks/use-authoring";
import { ROUTES } from "@/lib/constants";
import type { FileWaiting } from "@/types/authoring";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** One skill or context file with its changes, opening the list where they are decided. */
function FileRow({ file, href, changes }: { file: FileWaiting; href: string; changes: string }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <Link href={href} className="truncate font-medium">
        {file.name}
      </Link>
      <span className="text-muted-foreground shrink-0 text-xs">{changes}</span>
    </li>
  );
}

/**
 * What the authoring assistant suggested and nobody has decided, by what it
 * changes: per agent the reader may edit, its instruction, tool and setting
 * changes; per skill and context file, how many changes wait; and the skills it
 * proposed writing from nothing - each one click from where it is decided.
 */
export function AuthoringSuggestionsWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.authoring-suggestions");
  const { waiting, isLoading, error, refetch } = useWaitingSuggestions();
  const agents = waiting?.agents ?? [];
  const skillFiles = waiting?.skill_files ?? [];
  const contextFiles = waiting?.context_files ?? [];
  const newSkills =
    (waiting?.skills ?? 0) - skillFiles.reduce((sum, file) => sum + file.changes, 0);

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : agents.length === 0 &&
        skillFiles.length === 0 &&
        contextFiles.length === 0 &&
        newSkills === 0 ? (
        <WidgetEmptyBody
          icon={Sparkles}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {agents.map((row) => (
            <li key={row.agent_id} className="flex items-center justify-between gap-3 py-2">
              <Link
                href={`${ROUTES.AGENTS}/${row.agent_id}?tab=build`}
                className="truncate font-medium"
              >
                {row.name}
              </Link>
              <span className="text-muted-foreground shrink-0 text-xs">
                {t("counts", {
                  instructions: row.instructions,
                  tools: row.tools,
                  fields: row.fields ?? 0,
                })}
              </span>
            </li>
          ))}
          {skillFiles.map((file) => (
            <FileRow
              key={file.id}
              file={file}
              href={ROUTES.SKILLS}
              changes={t("skillChanges", { count: file.changes })}
            />
          ))}
          {newSkills > 0 && (
            <li className="py-2">
              <Link href={ROUTES.SKILLS} className="font-medium">
                {t("newSkills", { count: newSkills })}
              </Link>
            </li>
          )}
          {contextFiles.map((file) => (
            <FileRow
              key={file.id}
              file={file}
              href={ROUTES.CONTEXT}
              changes={t("contextChanges", { count: file.changes })}
            />
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
