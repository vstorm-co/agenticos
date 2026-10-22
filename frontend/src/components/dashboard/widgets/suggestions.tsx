"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { SuggestionCards } from "@/components/chat/suggestion-cards";
import { useOrganizations } from "@/hooks";
import { useSuggestions } from "@/hooks/use-suggestions";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What the nightly look proposed to the person (#2301), on their dashboard as
 * well as above their empty chat: the same cards, the same answers. Empty, it
 * says why - nothing proposed yet, or an organization with the look off.
 */
export function SuggestionsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.suggestions");
  const { suggestions } = useSuggestions();
  const { activeOrg } = useOrganizations();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {suggestions.length === 0 ? (
        <WidgetEmptyBody
          icon={Sparkles}
          title={t("empty.title")}
          description={
            activeOrg?.proactive_enabled ? t("empty.description") : t("empty.descriptionOff")
          }
        />
      ) : (
        <SuggestionCards agentId={null} />
      )}
    </WidgetFrame>
  );
}
