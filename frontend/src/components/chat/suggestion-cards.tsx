"use client";

import { ExternalLink, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useSuggestions } from "@/hooks/use-suggestions";
import { cn } from "@/lib/utils";
import {
  SuggestionMark,
  payloadText,
  urgentFirst,
  useSuggestionActions,
} from "./suggestion-actions";

/**
 * What the platform noticed overnight and proposes, above the empty chat (#2301).
 *
 * Made in the background; here the person only decides, through the same
 * actions the inbox offers. "Not now" declines it for good.
 */
export function SuggestionCards({
  agentId,
  className,
}: {
  agentId: string | null;
  className?: string;
}) {
  const t = useTranslations("chat.suggestions");
  const { suggestions: open } = useSuggestions();
  const { take, notNow, dialog } = useSuggestionActions(agentId);
  const suggestions = urgentFirst(open);

  if (suggestions.length === 0) return null;

  return (
    <section
      aria-label={t("label")}
      className={cn("mx-auto w-full max-w-2xl space-y-2", className)}
    >
      {suggestions.map((suggestion) => (
        <div
          key={suggestion.id}
          role="group"
          aria-label={suggestion.title}
          className="bg-muted/60 flex items-start gap-3 rounded-2xl p-3"
        >
          <SuggestionMark suggestion={suggestion} />
          <div className="min-w-0 flex-1 space-y-2">
            <p className="text-sm">
              {suggestion.urgent && (
                <span className="text-destructive mr-1.5 text-xs font-medium">{t("urgent")}</span>
              )}
              {suggestion.title}
              {suggestion.detail && (
                <span className="text-muted-foreground block text-xs">{suggestion.detail}</span>
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              {suggestion.kind === "finding" && payloadText(suggestion.payload.url) && (
                <Button asChild size="sm" variant="outline">
                  <a
                    href={payloadText(suggestion.payload.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    {t("open")}
                  </a>
                </Button>
              )}
              <Button type="button" size="sm" onClick={() => take(suggestion)}>
                {t(`take.${suggestion.kind}`)}
              </Button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => notNow(suggestion)}
            aria-label={t("notNow")}
            title={t("notNow")}
            className="text-muted-foreground hover:text-foreground rounded-md p-1"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      {dialog}
    </section>
  );
}
