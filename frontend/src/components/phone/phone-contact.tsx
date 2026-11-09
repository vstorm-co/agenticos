"use client";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useAgents } from "@/hooks/use-agents";
import { Button, Checkbox, Input, Label, Textarea } from "@/components/ui";
import {
  REPORT_LANGUAGES,
  isReportLanguage,
  type PhoneSettings,
  type PhoneContactConfig,
} from "@/lib/phone-api";
import { PhoneSelect } from "./phone-select";
export function PhoneContactForm({
  settings,
  pending,
  onSave,
}: {
  settings: PhoneSettings;
  pending: boolean;
  onSave: (data: PhoneContactConfig) => void;
}) {
  const t = useTranslations("phone");
  const locale = useLocale();
  const { agents } = useAgents();
  const [data, setData] = useState<PhoneContactConfig>(
    settings.contact ?? {
      identity_id: "",
      allow_calls: false,
      allow_reports: false,
      allow_transfers: false,
      agent_ids: [],
      allow_important: false,
      importance_instructions: "",
      escalation_delay_seconds: 0,
      report_language: locale === "pl" ? "pl-PL" : locale === "de" ? "de-DE" : "en-US",
      timezone: "UTC",
      quiet_start_hour: 22,
      quiet_end_hour: 8,
      calls_per_day: 3,
    },
  );
  if (!settings.sms_identities.length)
    return <p className="text-muted-foreground text-sm">{t("linkFirst")}</p>;
  const choices = [
    ...agents,
    ...data.agent_ids
      .filter((id) => !agents.some((agent) => agent.id === id))
      .map((id) => ({ id, name: t("unavailableAgent", { id }) })),
  ];
  const hours = Array.from({ length: 24 }, (_, hour) => ({
    id: String(hour),
    label: `${String(hour).padStart(2, "0")}:00`,
  }));
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(data);
      }}
      data-tour="phone-contact"
    >
      <PhoneSelect
        label={t("verifiedNumber")}
        value={data.identity_id}
        choices={settings.sms_identities}
        disabled={pending}
        onChange={(identity_id) => setData({ ...data, identity_id })}
      />
      {(["allow_calls", "allow_reports", "allow_transfers"] as const).map((field) => (
        <label key={field} className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={data[field]}
            disabled={pending}
            onCheckedChange={(value) => setData({ ...data, [field]: value === true })}
          />
          {t(field)}
        </label>
      ))}
      <fieldset className="space-y-2" disabled={pending}>
        <legend className="text-sm font-medium">{t("selectedAgents")}</legend>
        <p className="text-muted-foreground text-sm">{t("selectedAgentsHint")}</p>
        {choices.map((agent) => (
          <label key={agent.id} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={data.agent_ids.includes(agent.id)}
              onCheckedChange={(checked) =>
                setData({
                  ...data,
                  agent_ids:
                    checked === true
                      ? [...data.agent_ids, agent.id]
                      : data.agent_ids.filter((id) => id !== agent.id),
                })
              }
            />
            {agent.name}
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={data.allow_important}
            onCheckedChange={(checked) => setData({ ...data, allow_important: checked === true })}
          />
          {t("allowImportant")}
        </label>
        <Label htmlFor="phone-importance">{t("importanceInstructions")}</Label>
        <Textarea
          id="phone-importance"
          value={data.importance_instructions}
          maxLength={1200}
          required={data.allow_important}
          onChange={(event) => setData({ ...data, importance_instructions: event.target.value })}
        />
        <Label htmlFor="phone-delay">{t("escalationDelay")}</Label>
        <Input
          id="phone-delay"
          type="number"
          min={0}
          max={86400}
          value={data.escalation_delay_seconds}
          onChange={(event) =>
            setData({ ...data, escalation_delay_seconds: Number(event.target.value) })
          }
        />
        <p className="text-muted-foreground text-sm">{t("escalationHint")}</p>
      </fieldset>
      <PhoneSelect
        label={t("reportLanguage")}
        value={data.report_language}
        choices={REPORT_LANGUAGES.map((language) => ({
          id: language,
          label: t(`languages.${language}`),
        }))}
        onChange={(value) => {
          if (isReportLanguage(value)) setData({ ...data, report_language: value });
        }}
        disabled={pending}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="phone-zone">{t("timezone")}</Label>
          <Input
            id="phone-zone"
            value={data.timezone}
            disabled={pending}
            maxLength={64}
            onChange={(event) => setData({ ...data, timezone: event.target.value })}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="phone-contact-limit">{t("contactLimit")}</Label>
          <Input
            id="phone-contact-limit"
            type="number"
            min={1}
            max={20}
            value={data.calls_per_day}
            disabled={pending}
            onChange={(event) => setData({ ...data, calls_per_day: Number(event.target.value) })}
            required
          />
        </div>
        <PhoneSelect
          label={t("quietStart")}
          choices={hours}
          value={String(data.quiet_start_hour)}
          onChange={(value) => setData({ ...data, quiet_start_hour: Number(value) })}
          disabled={pending}
        />
        <PhoneSelect
          label={t("quietEnd")}
          choices={hours}
          value={String(data.quiet_end_hour)}
          onChange={(value) => setData({ ...data, quiet_end_hour: Number(value) })}
          disabled={pending}
        />
      </div>
      <Button
        type="submit"
        disabled={
          pending ||
          !data.identity_id ||
          data.quiet_start_hour === data.quiet_end_hour ||
          (data.allow_important && (!data.agent_ids.length || !data.importance_instructions.trim()))
        }
      >
        {t("saveContact")}
      </Button>
    </form>
  );
}
