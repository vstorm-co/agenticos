"use client";

import { useSyncExternalStore } from "react";
import { Check, Globe, Monitor, Moon, Sun } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type { LucideIcon } from "lucide-react";

import {
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { getLocaleFlag, getLocaleLabel, locales, type Locale } from "@/i18n";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { getResolvedTheme, useThemeStore, type Theme } from "@/stores/theme-store";

/**
 * The two preferences that belong to the person rather than to the page:
 * which theme, and which language.
 *
 * They used to be two icon buttons in a strip at the foot of the column,
 * beside search and the bell. That strip mixed two things a person does
 * ("find something", "what happened") with two they set once and forget, and
 * it filed all four under a row of unlabelled glyphs - so the language control
 * was a globe you had to click to find out what it did.
 *
 * Here they are named rows in the account menu, which is where every
 * comparable product keeps them and where the question they answer already
 * lives: this menu is "who am I, and how do I want this". Each one says its
 * current value on the trigger, so the menu answers "what language is this in"
 * without a second click.
 *
 * Submenus rather than a flat list of seven rows: the account menu's own
 * entries are the organization, the profile and signing out, and burying those
 * under three themes and three languages inverts what it is for.
 */

const THEME_ICON: Record<Theme, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

const THEME_LABEL: Record<Theme, string> = {
  light: "light",
  dark: "dark",
  system: "system",
};

/** Light, dark, or whatever the machine says - as a named submenu. */
export function AppearanceMenu() {
  const t = useTranslations("theme");
  const { theme, setTheme } = useThemeStore();
  // `false` on the server, `true` once hydrated - the same question
  // `ThemeToggle` asks, answered without a state write in an effect. The
  // subscribe callback never fires: the value cannot change after mount.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  const current: Theme = theme ?? "system";
  // Before hydration the stored preference is unknown, so the trigger shows the
  // resolved theme's own icon rather than guessing at the setting behind it.
  const TriggerIcon = mounted ? THEME_ICON[current] : THEME_ICON[getResolvedTheme(theme)];

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="gap-2">
        <TriggerIcon className="h-4 w-4 shrink-0" aria-hidden />
        <span className="flex-1">{t("appearance")}</span>
        {mounted ? (
          <span className="text-muted-foreground text-xs">{t(THEME_LABEL[current])}</span>
        ) : null}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-40">
        {(["light", "dark", "system"] as const).map((option) => {
          const Icon = THEME_ICON[option];
          return (
            <button
              key={option}
              type="button"
              role="menuitemradio"
              aria-checked={mounted && current === option}
              onClick={() => setTheme(option)}
              className="hover:bg-accent focus-visible:bg-accent flex w-full cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm outline-none"
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              <span className="flex-1">{t(THEME_LABEL[option])}</span>
              {mounted && current === option ? (
                <Check className="h-4 w-4 shrink-0" aria-hidden />
              ) : null}
            </button>
          );
        })}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

/**
 * Which language the console is in.
 *
 * Each row is a flag, the language's own name, and a tick on the one in use -
 * and nothing else. The previous list put a monospace locale code (`en`, `pl`)
 * on every row *except* the active one, where the tick went: two different
 * kinds of information in one column, so the eye read the codes as the thing
 * being chosen and the tick as an exception to it.
 *
 * The name is the language's own - Polski, Deutsch - because somebody looking
 * for their language is looking for the word they call it by, not for its
 * English name.
 */
export function LanguageMenu() {
  const t = useTranslations("common");
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="gap-2">
        <Globe className="h-4 w-4 shrink-0" aria-hidden />
        <span className="flex-1">{t("language")}</span>
        <span className="text-muted-foreground text-xs">{getLocaleLabel(locale)}</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-44">
        {locales.map((option) => (
          <button
            key={option}
            type="button"
            role="menuitemradio"
            aria-checked={option === locale}
            // Through `locale-navigation`, never `next/navigation`: the locale
            // lives in a cookie as well as in the path, and a switch that only
            // rewrites the URL survives exactly one navigation.
            onClick={() => router.push(pathname, { locale: option })}
            className="hover:bg-accent focus-visible:bg-accent flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2 py-1.5 text-left text-sm outline-none"
          >
            <span aria-hidden className="text-base leading-none">
              {getLocaleFlag(option)}
            </span>
            <span className="flex-1">{getLocaleLabel(option)}</span>
            {option === locale ? <Check className="h-4 w-4 shrink-0" aria-hidden /> : null}
          </button>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
