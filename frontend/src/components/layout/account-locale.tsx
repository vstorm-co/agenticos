"use client";

import { useEffect } from "react";
import { useLocale } from "next-intl";

import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useAuthStore } from "@/stores";

/**
 * Keeps the console in the language the account chose (#2301).
 *
 * A choice made on another device, or by an agent asked to switch, arrives as
 * `user.locale`; a page in any other language moves to it, through
 * `locale-navigation` so the cookie follows. An account that never chose has no
 * `locale`, and the cookie and the URL decide as they always did.
 */
export function AccountLocale() {
  const chosen = useAuthStore((state) => state.user?.locale ?? null);
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // With the query string, read here rather than through `useSearchParams` -
    // which would need a Suspense boundary around the whole dashboard - so a
    // switch inside `/chat?id=...` or `/agents/<id>?test=open` stays put.
    if (chosen && chosen !== locale) {
      router.replace(`${pathname}${window.location.search}`, { locale: chosen });
    }
  }, [chosen, locale, pathname, router]);

  return null;
}
