"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { adoptAccountAppearance } from "@/lib/account-appearance";
import { useUserAppearance } from "@/hooks/use-user-appearance";
import { qk } from "@/lib/query-keys";

/** Apply account reads, including edits made by an agent or another device. */
export function AccountAppearance() {
  const { owner, epoch, preferences } = useUserAppearance();
  const client = useQueryClient();
  useEffect(() => {
    const refresh = () => {
      if (owner) void client.invalidateQueries({ queryKey: qk.auth.appearance(owner) });
    };
    window.addEventListener("account-appearance-changed", refresh);
    return () => window.removeEventListener("account-appearance-changed", refresh);
  }, [client, owner]);
  useEffect(() => {
    if (owner && epoch !== undefined && preferences) {
      adoptAccountAppearance(owner, epoch, preferences);
    }
  }, [owner, epoch, preferences]);
  return null;
}
