"use client";

import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useWhatsAppTemplates } from "@/hooks/use-channel-bots";
import type { WhatsAppTemplate } from "@/types/channels";

type Choice = { name: string; language: string };

const NONE = "none";
/** A template is chosen by Meta's own name and language code. */
const keyOf = (choice: Choice) => `${choice.language}:${choice.name}`;

interface WhatsAppLateTemplateFieldProps {
  botId: string;
  value: Choice | null;
  /** The template saved on the bot, whose text shows while the list loads or when Meta dropped it. */
  stored?: WhatsAppTemplate | null;
  onChange: (value: Choice | null) => void;
  /** The server's refusal of the choice, if it named one. */
  error?: string;
}

/**
 * The template a WhatsApp bot answers in once the customer's 24-hour window has
 * closed (#2076), picked from the ones Meta lists for the account.
 *
 * Meta's list is the truth, so a failed load says so rather than offering an empty
 * list, and a template saved earlier that Meta no longer lists stays visible and is
 * marked, so it is not mistaken for a working one.
 */
export function WhatsAppLateTemplateField({
  botId,
  value,
  stored,
  onChange,
  error,
}: WhatsAppLateTemplateFieldProps) {
  const t = useTranslations("pages.channels");
  const { data, isLoading, isError } = useWhatsAppTemplates(botId);

  const listed = data ?? [];
  const chosen = value ? listed.find((entry) => keyOf(entry) === keyOf(value)) : undefined;
  const body =
    chosen?.body ?? (stored && value && keyOf(stored) === keyOf(value) ? stored.body : null);
  const unlisted = value !== null && data !== undefined && chosen === undefined;
  const label = (entry: Choice) =>
    t("whatsappLateTemplateOption", { name: entry.name, language: entry.language });

  return (
    <FormField
      label={t("whatsappLateTemplate")}
      htmlFor="edit-channel-whatsapp-late-template"
      error={error}
      description={t("whatsappLateTemplateHint")}
    >
      <Select
        value={value ? keyOf(value) : NONE}
        onValueChange={(next) => {
          const picked = listed.find((entry) => keyOf(entry) === next);
          if (next === NONE) onChange(null);
          else if (picked) onChange({ name: picked.name, language: picked.language });
        }}
      >
        <SelectTrigger id="edit-channel-whatsapp-late-template">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{t("whatsappLateTemplateNone")}</SelectItem>
          {listed.map((entry) => (
            <SelectItem key={keyOf(entry)} value={keyOf(entry)} textValue={label(entry)}>
              {label(entry)}
            </SelectItem>
          ))}
          {value && chosen === undefined && (
            <SelectItem
              value={keyOf(value)}
              textValue={label(value)}
              className={unlisted ? "text-warning" : undefined}
            >
              {unlisted
                ? t("whatsappLateTemplateUnlisted", { name: value.name, language: value.language })
                : label(value)}
            </SelectItem>
          )}
        </SelectContent>
      </Select>
      {body && (
        <p className="text-muted-foreground mt-1.5 text-xs break-words whitespace-pre-wrap">
          {body}
        </p>
      )}
      {isLoading && (
        <p className="text-muted-foreground mt-1.5 text-xs">{t("whatsappLateTemplateLoading")}</p>
      )}
      {isError && (
        <p role="alert" className="text-destructive mt-1.5 text-xs">
          {t("whatsappLateTemplateFailed")}
        </p>
      )}
      {data?.length === 0 && (
        <p className="text-muted-foreground mt-1.5 text-xs">{t("whatsappLateTemplateEmpty")}</p>
      )}
    </FormField>
  );
}
