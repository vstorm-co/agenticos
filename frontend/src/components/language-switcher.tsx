"use client";

import { Check, Globe } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, usePathname } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { locales, defaultLocale, type Locale, getLocaleLabel, getLocaleFlag } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * Build a path for the given locale, preserving the rest of the route.
 * Handles `localePrefix: "as-needed"` - default locale has no prefix.
 */
function buildLocalizedPath(pathname: string, newLocale: Locale): string {
  const segments = pathname.split("/").filter(Boolean);
  const first = segments[0];
  if (first && (locales as readonly string[]).includes(first)) {
    segments.shift();
  }
  const rest = segments.join("/");
  if (newLocale === defaultLocale) {
    return rest ? `/${rest}` : "/";
  }
  return rest ? `/${newLocale}/${rest}` : `/${newLocale}`;
}

/**
 * Icon-button language switcher - globe icon trigger + Radix dropdown.
 * Designed for the app toolbar (header), where it sits alongside other
 * icon-only controls. Matches the flat toolbar aesthetic (h-9 w-9, rounded-lg,
 * hover:bg-accent) and reuses the shared DropdownMenu so its menu styling is
 * consistent with the org/user menus.
 */
export function LanguageSwitcherIcon() {
  const t = useTranslations("common");
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();

  const handleChange = (newLocale: Locale) => {
    router.push(buildLocalizedPath(pathname, newLocale));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("language")}
          className={cn(
            "text-muted-foreground hover:text-foreground hover:bg-accent",
            "focus-visible:ring-ring inline-flex h-9 w-9 items-center justify-center rounded-lg",
            "transition-colors outline-none focus-visible:ring-1",
          )}
        >
          <Globe className="h-[1.1rem] w-[1.1rem]" aria-hidden />
          <span className="sr-only">{getLocaleLabel(locale)}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        {locales.map((loc) => {
          const active = loc === locale;
          return (
            <DropdownMenuItem key={loc} onSelect={() => handleChange(loc)} className="gap-2.5">
              <span aria-hidden className="text-base leading-none">
                {getLocaleFlag(loc)}
              </span>
              <span className="flex-1">{getLocaleLabel(loc)}</span>
              {active ? (
                <Check className="text-foreground h-4 w-4" />
              ) : (
                <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                  {loc}
                </span>
              )}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
