"use client";
import { LanguageSwitcherIcon } from "@/components/language-switcher";
import { useChooseLocale } from "@/hooks/use-choose-locale";
export function StartLanguage() {
  const choose = useChooseLocale();
  return <LanguageSwitcherIcon onLocaleChange={choose} />;
}
