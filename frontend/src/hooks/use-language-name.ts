"use client";

import { useLocale } from "next-intl";
import { useMemo } from "react";

/** A language's name in the reader's own language, or its code where unnamed. */
export function useLanguageName(): (code: string) => string {
  const locale = useLocale();
  return useMemo(() => {
    // `fallback: "code"` answers a code it cannot name with the code itself.
    const names = new Intl.DisplayNames([locale], { type: "language", fallback: "code" });
    return (code: string) => names.of(code)!;
  }, [locale]);
}
