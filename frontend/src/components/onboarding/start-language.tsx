"use client";

import { useLocale, useTranslations } from "next-intl";
import { getLocaleLabel, locales } from "@/i18n";
import { useChooseLocale } from "@/hooks/use-choose-locale";

export function StartLanguage() {
  const locale = useLocale();
  const t = useTranslations("common");
  const choose = useChooseLocale();
  return (
    <label className="text-muted-foreground flex items-center gap-2 text-sm">
      {t("language")}
      <select
        className="border-border bg-background rounded-md border px-2 py-1"
        value={locale}
        onChange={(event) => {
          const next = locales.find((item) => item === event.target.value);
          if (next) choose(next);
        }}
      >
        {locales.map((item) => (
          <option key={item} value={item}>
            {getLocaleLabel(item)}
          </option>
        ))}
      </select>
    </label>
  );
}
