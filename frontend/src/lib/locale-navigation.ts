import { createNavigation } from "next-intl/navigation";

import { routing } from "@/lib/locale-routing";

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
export const { usePathname, useRouter } = createNavigation(routing);
