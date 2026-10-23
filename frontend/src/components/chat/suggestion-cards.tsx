"use client";

import { useState } from "react";
import { Bot, CalendarClock, ExternalLink, Package, Radar, UserRound, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { useMcpCatalog } from "@/hooks";
import { useSuggestions } from "@/hooks/use-suggestions";
import { getErrorMessage } from "@/lib/api-error";
import type { Suggestion, SuggestionKind } from "@/lib/suggestions-api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";

/** Weekly on Monday at 8:00 UTC, for a repeated request the night gave no cadence. */
const WEEKLY = { schedule_kind: "cron", cron_expression: "0 8 * * 1" } as const;

const ICONS: Record<SuggestionKind, typeof Bot> = {
  routine: CalendarClock,
  agent: Bot,
  profile: UserRound,
  role_pack: Package,
  finding: Radar,
};

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/**
 * What the platform noticed overnight and proposes, above the empty chat (#2301).
 *
 * Made in the background; here the person only decides. A routine opens the
 * routine dialog filled in, an agent is a question to the Architect, a profile
 * update and a role pack are saved by the server. A watch's finding opens where
 * it lives and is marked done. "Not now" declines it for good.
 */
export function SuggestionCards({
  agentId,
  items,
  className,
}: {
  agentId: string | null;
  /** Which of the person's open ones to show; all of them when left out. */
  items?: Suggestion[];
  className?: string;
}) {
  const t = useTranslations("chat.suggestions");
  const tErrors = useTranslations("errors");
  const { suggestions: open, accept, dismiss } = useSuggestions();
  const { servers } = useMcpCatalog();
  // What cannot wait leads, whatever order it arrived in.
  const suggestions = [...(items ?? open)].sort(
    (a, b) => Number(b.urgent === true) - Number(a.urgent === true),
  );
  const ask = useArchitectAskStore((state) => state.ask);
  const [routine, setRoutine] = useState<TriggerTemplate | null>(null);

  if (suggestions.length === 0) return null;

  const decide = async (work: () => Promise<unknown>) => {
    try {
      await work();
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };

  const take = (suggestion: Suggestion) =>
    decide(async () => {
      if (suggestion.kind === "routine") {
        const cron = text(suggestion.payload.cron);
        setRoutine({
          key: `suggestion-${suggestion.id}`,
          label: suggestion.title,
          description: "",
          prompt: text(suggestion.payload.prompt),
          trigger_type: "schedule",
          suggested_cadence: cron ? { schedule_kind: "cron", cron_expression: cron } : WEEKLY,
        });
      } else if (suggestion.kind === "agent") {
        ask(t("agentAsk", { request: text(suggestion.payload.request) }));
      }
      await accept(suggestion.id);
      if (suggestion.kind === "profile") {
        const user = useAuthStore.getState().user;
        if (user) useAuthStore.getState().setUser({ ...user, ...suggestion.payload });
        toast.success(t("profileSaved"));
      } else if (suggestion.kind === "role_pack") {
        toast.success(t("packInstalling"));
      }
    });

  return (
    <section
      aria-label={t("label")}
      className={cn("mx-auto w-full max-w-2xl space-y-2", className)}
    >
      {suggestions.map((suggestion) => {
        const Icon = ICONS[suggestion.kind];
        const server =
          suggestion.kind === "finding"
            ? servers.find((entry) => entry.key === text(suggestion.payload.server))
            : undefined;
        return (
          <div
            key={suggestion.id}
            role="group"
            aria-label={suggestion.title}
            className="bg-muted/60 flex items-start gap-3 rounded-2xl p-3"
          >
            <span className="bg-card text-foreground shadow-card flex h-8 w-8 shrink-0 items-center justify-center rounded-xl">
              {server ? (
                <McpServerIcon
                  icon={server.icon}
                  name={server.name}
                  url={server.url}
                  className="h-4 w-4"
                />
              ) : (
                <Icon className="h-4 w-4" aria-hidden />
              )}
            </span>
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
                {suggestion.kind === "finding" && text(suggestion.payload.url) && (
                  <Button asChild size="sm" variant="outline">
                    <a
                      href={text(suggestion.payload.url)}
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
              onClick={() => decide(() => dismiss(suggestion.id))}
              aria-label={t("notNow")}
              title={t("notNow")}
              className="text-muted-foreground hover:text-foreground rounded-md p-1"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
      {routine && (
        <TriggerFormDialog
          agentId={agentId}
          open
          onOpenChange={(open) => !open && setRoutine(null)}
          initialTemplate={routine}
        />
      )}
    </section>
  );
}
