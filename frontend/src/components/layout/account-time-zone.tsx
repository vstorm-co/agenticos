"use client";

import { useEffect, useRef } from "react";

import { useSaveAgentContext } from "@/hooks/use-account-profile";
import { useAuthStore } from "@/stores";

/**
 * Records the browser's time zone on an account that has none (#2301).
 *
 * Every agent reads a person's times in it - "every Monday at 9" is their 9 - and
 * nobody should have to type `Europe/Warsaw` for that. Only when the account has
 * none: one chosen in Settings, or recorded on another device, is the person's
 * and is not overwritten by whichever laptop they opened last. A failed save is
 * left for the next page load to try again; nothing is waiting on it.
 */
export function AccountTimeZone() {
  const user = useAuthStore((state) => state.user);
  const save = useSaveAgentContext();
  const tried = useRef<string | null>(null);

  useEffect(() => {
    if (!user || user.time_zone || tried.current === user.id) return;
    tried.current = user.id;
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (zone) save({ time_zone: zone }).catch(() => undefined);
  }, [user, save]);

  return null;
}
