"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { LoadingState } from "@/components/states";
import { Button, FormField, Input, Label, SectionHeading, Switch, Textarea } from "@/components/ui";
import { useModelProviders, usePermissions } from "@/hooks";
import { useAssistant, useUpdateAssistant } from "@/hooks/use-assistant";
import { readPreferences, resetSilenced, setBubblesOff } from "@/lib/assistant-bubbles";
import { Perm } from "@/types/permissions";
import type { AssistantState } from "@/types/assistant";

/**
 * Settings → Assistant (#2063): the reader's own tips, and - for whoever may
 * change the organization's settings - what the AI Architect is called, how it
 * greets people, which model it runs on, and whether it is there at all.
 */
export function AssistantSettings() {
  const t = useTranslations("assistantSettings");
  const { assistant, isLoading } = useAssistant();
  if (isLoading) return <LoadingState variant="skeleton-panel" rows={4} />;
  if (!assistant) return null;
  return (
    <div className="space-y-8">
      {assistant.can_use ? (
        <YourTips />
      ) : (
        <p className="text-muted-foreground text-sm">{t("notForYou")}</p>
      )}
      {assistant.can_configure && <ForTheOrganization assistant={assistant} />}
    </div>
  );
}

function YourTips() {
  const t = useTranslations("assistantSettings");
  const [preferences, setPreferences] = useState(readPreferences);
  return (
    <section className="space-y-4">
      <SectionHeading title={t("yours")} description={t("yoursDescription")} />
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
    </section>
  );
}

function ForTheOrganization({ assistant }: { assistant: AssistantState }) {
  const t = useTranslations("assistantSettings");
  const { can } = usePermissions();
  const { profiles, profilesStatus } = useModelProviders();
  const update = useUpdateAssistant();
  const [name, setName] = useState(assistant.name);
  const [greeting, setGreeting] = useState(assistant.greeting ?? "");
  const enabled = assistant.status !== "disabled";
  const dirty = name !== assistant.name || greeting !== (assistant.greeting ?? "");

  return (
    <section className="space-y-5" data-tour="assistant-settings">
      <SectionHeading title={t("organization")} description={t("organizationDescription")} />
      <div className="flex items-center justify-between gap-4">
        <Label htmlFor="assistant-enabled">{t("enabled")}</Label>
        <Switch
          id="assistant-enabled"
          checked={enabled}
          disabled={update.isPending}
          onCheckedChange={(on) => update.mutate({ enabled: on })}
        />
      </div>
      {assistant.status === "needs_model" && (
        <p className="text-muted-foreground text-sm">{t("needsModel")}</p>
      )}
      <div className="space-y-2">
        <Label>{t("model")}</Label>
        <ModelProfilePicker
          allowAdd={can(Perm.connectionsManage)}
          profiles={profiles}
          profilesStatus={profilesStatus}
          value={assistant.model_profile_id}
          onChange={(model_profile_id) => update.mutate({ model_profile_id })}
          disabled={update.isPending}
        />
      </div>
      <FormField label={t("name")} htmlFor="assistant-name">
        <Input
          id="assistant-name"
          value={name}
          maxLength={128}
          onChange={(e) => setName(e.target.value)}
        />
      </FormField>
      <FormField label={t("greeting")} htmlFor="assistant-greeting" description={t("greetingHint")}>
        <Textarea
          id="assistant-greeting"
          value={greeting}
          rows={3}
          maxLength={500}
          onChange={(e) => setGreeting(e.target.value)}
        />
      </FormField>
      <Button
        disabled={!dirty || name.trim() === "" || update.isPending}
        onClick={() => update.mutate({ name: name.trim(), greeting: greeting.trim() || null })}
      >
        {t("save")}
      </Button>
    </section>
  );
}
