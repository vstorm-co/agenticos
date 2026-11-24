"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SectionCard } from "@/components/settings/settings-section";
import { Button, Label, Switch } from "@/components/ui";
import { readPreferences, resetSilenced, setBubblesOff } from "@/lib/assistant-bubbles";

/** Personal, browser-local tips. Organization assistant settings live in AI & services. */
export function AssistantSettings() {
  const t = useTranslations("assistantSettings");
  const [preferences, setPreferences] = useState(readPreferences);
  return (
    // A card like every other settings tab's section, not headings loose on
    // the page.
    <SectionCard title={t("yours")} description={t("yoursDescription")}>
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="assistant-tips">{t("showTips")}</Label>
          <Switch
            id="assistant-tips"
            checked={!preferences.off}
            onCheckedChange={(on) => {
              setBubblesOff(!on);
              setPreferences(readPreferences());
            }}
          />
        </div>
        {preferences.silenced.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetSilenced();
              setPreferences(readPreferences());
            }}
          >
            {t("unsilence", { count: preferences.silenced.length })}
          </Button>
        )}
      </div>
    </SectionCard>
  );
}
