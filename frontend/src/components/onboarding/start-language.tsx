"use client";
import { LanguageSwitcherIcon } from "@/components/language-switcher";
import { useChooseLocale } from "@/hooks/use-choose-locale";
import { hasLocaleChoice } from "@/lib/locales";

/** The start page's language control - absent when the deployment serves one locale. */
export function StartLanguage() {
  return hasLocaleChoice ? <StartLanguageChoice /> : null;
}

function StartLanguageChoice() {
  const choose = useChooseLocale();
  return <LanguageSwitcherIcon onLocaleChange={choose} />;
}
