"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SectionCard } from "@/components/settings/settings-section";
import { Badge, Button, Label, Switch } from "@/components/ui";
import { useOrganizations } from "@/hooks";
import { useSaveProactiveOptOut } from "@/hooks/use-account-profile";
import { useSuggestionHistory } from "@/hooks/use-suggestions";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores";

/**
 * The person's side of the nightly look (#2301): whether it reaches them at all,
 * and everything it proposed - what they took, what they declined, and a way to
 * bring a declined one back to the chat.
 */
export function YourSuggestions() {
  const t = useTranslations("assistantSettings.suggestions");
  const tErrors = useTranslations("errors");
  const optedOut = useAuthStore((state) => state.user?.proactive_opt_out ?? false);
  const saveOptOut = useSaveProactiveOptOut();
  const { activeOrg } = useOrganizations();
  const { history, restore } = useSuggestionHistory();
  const [saving, setSaving] = useState(false);

  const act = async (work: () => Promise<unknown>, done: string) => {
    setSaving(true);
    try {
      await work();
      toast.success(done);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SectionCard title={t("title")} description={t("description")}>
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="suggestions-for-me">{t("forMe")}</Label>
            {activeOrg?.proactive_enabled === false && (
              <p className="text-muted-foreground text-xs">{t("orgOff")}</p>
            )}
          </div>
          <Switch
            id="suggestions-for-me"
            checked={!optedOut}
            disabled={saving}
            onCheckedChange={(on) =>
              act(() => saveOptOut(!on), on ? t("turnedOn") : t("turnedOff"))
            }
          />
        </div>
        {history.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="divide-foreground/10 divide-y">
            {history.map((suggestion) => (
              <li key={suggestion.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{suggestion.title}</p>
                  {suggestion.detail && (
                    <p className="text-muted-foreground truncate text-xs">{suggestion.detail}</p>
                  )}
                </div>
                <Badge variant="secondary">{t(`status.${suggestion.status}`)}</Badge>
                {suggestion.status === "dismissed" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={saving}
                    onClick={() => act(() => restore(suggestion.id), t("restored"))}
                  >
                    {t("restore")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </SectionCard>
  );
}
