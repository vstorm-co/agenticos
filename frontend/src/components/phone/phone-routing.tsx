"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Checkbox, Input, Label } from "@/components/ui";
import type { PhoneSettings, PhoneEndpointConfig } from "@/lib/phone-api";
import { PhoneSelect } from "./phone-select";
export function PhoneRouting({
  settings,
  pending,
  onSave,
}: {
  settings: PhoneSettings;
  pending: boolean;
  onSave: (botId: string, data: PhoneEndpointConfig) => void;
}) {
  const t = useTranslations("phone");
  const [bot, setBot] = useState("");
  return (
    <div className="space-y-3" data-tour="channels-phone">
      <PhoneSelect
        label={t("twilioBot")}
        value={bot}
        onChange={setBot}
        choices={settings.sms_bots}
        disabled={pending}
      />
      {bot ? (
        <EndpointEditor
          key={bot}
          botId={bot}
          settings={settings}
          pending={pending}
          onSave={onSave}
        />
      ) : (
        <p className="text-muted-foreground text-sm">{t("routingHint")}</p>
      )}
    </div>
  );
}
function EndpointEditor({
  botId,
  settings,
  pending,
  onSave,
}: {
  botId: string;
  settings: PhoneSettings;
  pending: boolean;
  onSave: (botId: string, data: PhoneEndpointConfig) => void;
}) {
  const t = useTranslations("phone");
  const current = settings.endpoints.find((row) => row.bot_id === botId);
  const [data, setData] = useState<PhoneEndpointConfig>(
    current ?? {
      enabled: false,
      inbound_embed_id: null,
      max_call_seconds: 300,
      calls_per_hour: 10,
      calls_per_day: 30,
      max_concurrent: 2,
      daily_budget_usd: 5,
      price_per_minute_usd: "",
      transfer_contact_ids: [],
    },
  );
  const contacts = [
    ...settings.transfer_contacts,
    ...data.transfer_contact_ids
      .filter((id) => !settings.transfer_contacts.some((contact) => contact.id === id))
      .map((id) => ({ id, label: t("unavailableContact", { id }) })),
  ];
  const fields = [
    "max_call_seconds",
    "calls_per_hour",
    "calls_per_day",
    "max_concurrent",
    "daily_budget_usd",
    "price_per_minute_usd",
  ] as const;
  const limits = {
    max_call_seconds: [60, 900],
    calls_per_hour: [1, 120],
    calls_per_day: [1, 1000],
    max_concurrent: [1, 10],
    daily_budget_usd: [0.000001, 1000],
    price_per_minute_usd: [0.000001, 10],
  } as const;
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(botId, data);
      }}
    >
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={data.enabled}
          disabled={pending}
          onCheckedChange={(enabled) => setData({ ...data, enabled: enabled === true })}
        />
        {t("enableRouting")}
      </label>
      <PhoneSelect
        label={t("publicExposure")}
        value={data.inbound_embed_id ?? ""}
        choices={settings.public_voice_embeds}
        onChange={(value) => setData({ ...data, inbound_embed_id: value || null })}
        optional
        disabled={pending}
      />
      <p className="text-muted-foreground text-xs">{t("inboundPrivacy")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <div key={field} className="space-y-1">
            <Label htmlFor={`phone-${field}`}>{t(field)}</Label>
            <Input
              id={`phone-${field}`}
              type="number"
              min={limits[field][0]}
              max={limits[field][1]}
              step={field.includes("usd") ? 0.000001 : 1}
              value={data[field]}
              disabled={pending}
              onChange={(event) =>
                setData({
                  ...data,
                  [field]: field.includes("usd") ? event.target.value : Number(event.target.value),
                })
              }
              required
            />
          </div>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{t("costHint")}</p>
      <fieldset className="space-y-2">
        <legend className="text-sm">{t("transferTargets")}</legend>
        {contacts.map((contact) => (
          <label key={contact.id} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={data.transfer_contact_ids.includes(contact.id)}
              disabled={pending}
              onCheckedChange={(value) =>
                setData({
                  ...data,
                  transfer_contact_ids:
                    value === true
                      ? [...data.transfer_contact_ids, contact.id]
                      : data.transfer_contact_ids.filter((id) => id !== contact.id),
                })
              }
            />
            {contact.label}
          </label>
        ))}
      </fieldset>
      <Button type="submit" disabled={pending || Number(data.price_per_minute_usd) <= 0}>
        {t("saveRouting")}
      </Button>
      {current ? (
        <dl className="space-y-2 text-xs">
          {[
            [t("endpointId"), current.id],
            [t("inboundUrl"), current.inbound_url],
            [t("statusUrl"), current.status_url],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="break-all select-all">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </form>
  );
}
