"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { signalNavigation } from "@/lib/navigation-progress";

/** Keep Next's routing contract while announcing button/table-driven navigation. */
export function useConsoleRouter(): ReturnType<typeof useRouter> {
  const router = useRouter();
  return useMemo(
    () => ({
      ...router,
      push: (...args: Parameters<typeof router.push>) => {
        signalNavigation(args[0]);
        return router.push(...args);
      },
      replace: (...args: Parameters<typeof router.replace>) => {
        signalNavigation(args[0]);
        return router.replace(...args);
      },
    }),
    [router],
  );
}
