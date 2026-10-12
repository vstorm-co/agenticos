"use client";

import { useState } from "react";
import { ListOrdered } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SectionCard } from "@/components/settings/settings-section";
import { Switch } from "@/components/ui";
import { apiClient, ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

/**
 * How the console's chat behaves for this person (#2087).
 *
 * A message typed while the agent works joins the running turn by default and
 * reaches it at the next step. Somebody who would rather finish one exchange
 * before starting the next turns that into the queue instead - their habit, so
 * it is stored on their account and follows them to every device. Channels have
 * no such switch: a chat app has no queue to show, so a message there always
 * joins the running turn.
 */
export function ChatPreferences() {
  const t = useTranslations("pages.settings");
  const tErrors = useTranslations("errors");
  const { user, setUser } = useAuthStore();
  const [saving, setSaving] = useState(false);
  if (!user) return null;

  const toggle = async (queue: boolean) => {
    setSaving(true);
    try {
      setUser(await apiClient.patch<User>("/users/me", { queue_while_working: queue }));
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedSavePreference"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <SectionCard title={t("chatPreferences")} description={t("chatPreferencesDescription")}>
      <div className="flex items-start gap-3">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <ListOrdered className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-foreground text-sm font-medium">{t("queueWhileWorking")}</p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {t("queueWhileWorkingHint")}
          </p>
        </div>
        <Switch
          aria-label={t("queueWhileWorking")}
          checked={user.queue_while_working ?? false}
          disabled={saving}
          onCheckedChange={toggle}
        />
      </div>
    </SectionCard>
  );
}
