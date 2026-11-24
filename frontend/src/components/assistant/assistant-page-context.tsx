"use client";

import { useState } from "react";
import { ChevronDown, Eye, EyeOff } from "lucide-react";
import { useTranslations } from "next-intl";

import type { AssistantPageContext } from "@/lib/assistant-page-context";

interface AssistantPageContextProps {
  page: AssistantPageContext;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

/** Shows exactly which registered page details the next question will include. */
export function AssistantPageContextBar({
  page,
  enabled,
  onEnabledChange,
}: AssistantPageContextProps) {
  const t = useTranslations("assistantWidget.pageContext");
  const [expanded, setExpanded] = useState(false);
  return (
    <section data-tour="assistant-page-context" className="border-border border-b px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={t("include")}
          onClick={() => onEnabledChange(!enabled)}
          className="text-muted-foreground hover:text-foreground flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left text-xs"
        >
          {enabled ? (
            <Eye className="size-3.5 shrink-0" />
          ) : (
            <EyeOff className="size-3.5 shrink-0" />
          )}
          <span className="min-w-0 truncate">
            {enabled
              ? t("using", { page: page.resource?.title || page.title || page.path })
              : t("off")}
          </span>
        </button>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 rounded-md py-1 text-xs"
        >
          {t("view")}
          <ChevronDown className={expanded ? "size-3.5 rotate-180" : "size-3.5"} />
        </button>
      </div>
      {expanded && (
        <div className="text-muted-foreground max-h-48 space-y-2 overflow-y-auto pt-2 text-xs">
          <p>{t("explanation")}</p>
          <dl className="space-y-1 break-words">
            <dt className="text-foreground font-medium">{t("page")}</dt>
            <dd>{page.title || page.path}</dd>
            <dd>{page.path}</dd>
            {page.resource && (
              <>
                <dt className="text-foreground font-medium">{t("record")}</dt>
                <dd>{page.resource.title || page.resource.id}</dd>
              </>
            )}
            {page.view && (
              <>
                <dt className="text-foreground font-medium">{t("viewLabel")}</dt>
                <dd>{page.view}</dd>
              </>
            )}
            {page.filters &&
              Object.entries(page.filters).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-foreground font-medium">{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            {!!page.selected_ids?.length && (
              <>
                <dt className="text-foreground font-medium">{t("selected")}</dt>
                <dd>{page.selected_ids.join(", ")}</dd>
              </>
            )}
          </dl>
          {page.summary && <p className="whitespace-pre-wrap">{page.summary}</p>}
          {page.selected_text && (
            <blockquote className="border-border border-l-2 pl-2 whitespace-pre-wrap">
              {page.selected_text}
            </blockquote>
          )}
        </div>
      )}
    </section>
  );
}
