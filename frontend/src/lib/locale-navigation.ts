import { createNavigation } from "next-intl/navigation";
import { useMemo } from "react";

import { routing, localePrefixOf } from "@/lib/locale-routing";
import { signalNavigation } from "@/lib/navigation-progress";

/**
 * Locale-aware navigation, built from the one routing config.
 *
 * `router.push(pathname, { locale })` does the two things a language switch needs
 * and that `next/navigation` cannot: it prefixes the path for the target locale,
 * and it writes the locale cookie the middleware reads. Pushing a hand-built path
 * did only the first, so the choice survived exactly until a link dropped the
 * prefix (#285).
 *
 * `usePathname` is next-intl's, which answers without the locale prefix - which is
 * what `push` expects.
 */
const navigation = createNavigation(routing);
export const { getPathname, usePathname } = navigation;

export function useRouter(): ReturnType<typeof navigation.useRouter> {
  const router = navigation.useRouter();
  return useMemo(
    () => ({
      ...router,
      push: (...args: Parameters<typeof router.push>) => {
        signalNavigation(
          navigation.getPathname({
            href: args[0],
            locale:
              args[1]?.locale ?? localePrefixOf(window.location.pathname) ?? routing.defaultLocale,
          }),
        );
        return router.push(...args);
      },
      replace: (...args: Parameters<typeof router.replace>) => {
        signalNavigation(
          navigation.getPathname({
            href: args[0],
            locale:
              args[1]?.locale ?? localePrefixOf(window.location.pathname) ?? routing.defaultLocale,
          }),
        );
        return router.replace(...args);
      },
    }),
    [router],
  );
}
