"use client";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Checkbox, Input, Label } from "@/components/ui";
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
  const [data, setData] = useState<PhoneContactConfig>(
    settings.contact ?? {
      identity_id: "",
      allow_calls: false,
      allow_reports: false,
      allow_transfers: false,
      report_language: locale === "pl" ? "pl-PL" : locale === "de" ? "de-DE" : "en-US",
      timezone: "UTC",
      quiet_start_hour: 22,
      quiet_end_hour: 8,
      calls_per_day: 3,
    },
  );
  if (!settings.sms_identities.length)
    return <p className="text-muted-foreground text-sm">{t("linkFirst")}</p>;
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
        disabled={pending || !data.identity_id || data.quiet_start_hour === data.quiet_end_hour}
      >
        {t("saveContact")}
      </Button>
    </form>
  );
}
