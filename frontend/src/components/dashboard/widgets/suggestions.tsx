"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { SuggestionCards } from "@/components/chat/suggestion-cards";
import { useOrganizations } from "@/hooks";
import { useSuggestions } from "@/hooks/use-suggestions";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many the card shows; the rest are a link away, in the inbox. */
const SHOWN = 4;

/**
 * The person's briefing (#2301): what their watches found and what the nightly
 * look proposed, what cannot wait first - the same cards as the inbox and the
 * empty chat, the same answers. Empty, it says why.
 */
export function SuggestionsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.suggestions");
  const { suggestions } = useSuggestions();
  const { activeOrg } = useOrganizations();
  const first = [...suggestions]
    .sort((a, b) => Number(b.urgent === true) - Number(a.urgent === true))
    .slice(0, SHOWN);
  const on = activeOrg?.proactive_enabled === true || activeOrg?.proactive_watches_enabled === true;

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {suggestions.length === 0 ? (
        <WidgetEmptyBody
          icon={Sparkles}
          title={t("empty.title")}
          description={on ? t("empty.description") : t("empty.descriptionOff")}
        />
      ) : (
        <div className="space-y-2">
          <SuggestionCards agentId={null} items={first} className="max-w-none" />
          {suggestions.length > SHOWN && (
            <Link
              href={ROUTES.INBOX}
              className="text-muted-foreground hover:text-foreground block text-center text-xs"
            >
              {t("more", { count: suggestions.length - SHOWN })}
            </Link>
          )}
        </div>
      )}
    </WidgetFrame>
  );
}
