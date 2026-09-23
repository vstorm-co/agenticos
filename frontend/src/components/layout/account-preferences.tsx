"use client";

import { Globe, Monitor, Moon, Sun } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type { LucideIcon } from "lucide-react";

import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { useMounted } from "@/hooks/use-mounted";
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
 *
 * Each choice is a Radix `RadioItem`, not a `<button role="menuitemradio">`.
 * The hand-rolled version looked identical and was unreachable: Radix builds a
 * roving-focus collection from its own primitives, so a plain button inside a
 * menu is skipped by the arrow keys while the menu suppresses Tab - which made
 * both of these keyboard-inaccessible the moment they moved in here.
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
  // `false` on the server, `true` once hydrated - `useMounted` says why.
  const mounted = useMounted();

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
        <DropdownMenuRadioGroup
          value={mounted ? current : undefined}
          onValueChange={(next) => setTheme(next as Theme)}
        >
          {(["light", "dark", "system"] as const).map((option) => {
            const Icon = THEME_ICON[option];
            return (
              <DropdownMenuRadioItem key={option} value={option} className="gap-2">
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {t(THEME_LABEL[option])}
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
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
        <DropdownMenuRadioGroup
          value={locale}
          // Through `locale-navigation`, never `next/navigation`: the locale
          // lives in a cookie as well as in the path, and a switch that only
          // rewrites the URL survives exactly one navigation.
          onValueChange={(next) => router.push(pathname, { locale: next as Locale })}
        >
          {locales.map((option) => (
            <DropdownMenuRadioItem key={option} value={option} className="gap-2.5">
              <span aria-hidden className="text-base leading-none">
                {getLocaleFlag(option)}
              </span>
              {getLocaleLabel(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
