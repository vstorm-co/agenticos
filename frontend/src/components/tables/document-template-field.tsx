"use client";

import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";

/** Built-in bodies are translated when selected; stored templates remain the user's text. */
export const DOCUMENT_TEMPLATE_KEYS = ["blank", "note", "meeting", "brief"] as const;

export function DocumentTemplateField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("tables.markdown");
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("template")}</Label>
      <Select value="" onValueChange={(key) => onChange(t(`templates.${key}.body`))}>
        <SelectTrigger aria-label={t("chooseTemplate")}>
          <SelectValue placeholder={t("chooseTemplate")} />
        </SelectTrigger>
        <SelectContent>
          {DOCUMENT_TEMPLATE_KEYS.map((key) => (
            <SelectItem key={key} value={key}>
              {t(`templates.${key}.label`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Textarea
        id={id}
        value={value}
        maxLength={100000}
        rows={6}
        onChange={(event) => onChange(event.target.value)}
      />
      <p className="text-muted-foreground text-xs">{t("templateHint")}</p>
    </div>
  );
}
