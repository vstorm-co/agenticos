"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { adoptAccountLocale } from "@/lib/account-locale";
import { saveAccountLocale } from "@/lib/account-locale-api";
import { getErrorMessage } from "@/lib/api-error";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import type { Locale } from "@/lib/locales";
import { useAuthStore } from "@/stores";

/**
 * Switch the console's language and keep the choice on the account (#2301).
 *
 * The store takes the choice before the request leaves, so `AccountLocale` -
 * which follows the account - does not pull the page back to the old language
 * while the save is in flight. A save that fails says so; the page stays in the
 * language picked, held by the cookie as it was before accounts kept one.
 */
export function useChooseLocale(): (next: Locale) => void {
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const pathname = usePathname();
  const signedIn = useAuthStore((state) => state.user !== null);

  return useCallback(
    (next: Locale) => {
      if (signedIn) {
        adoptAccountLocale(next);
        saveAccountLocale(next).catch((error: unknown) =>
          toast.error(getErrorMessage(error, tErrors)),
        );
      }
      router.push(pathname, { locale: next });
    },
    [pathname, router, signedIn, tErrors],
  );
}
