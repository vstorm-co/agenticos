import type { Metadata } from "next";

import { DiagnosticsPresence } from "@/components/layout/diagnostics-presence";
import { AccountAppearance } from "@/components/layout/account-appearance";
import { AccountLocale } from "@/components/layout/account-locale";

/** Pages the desktop app draws in windows of its own; nothing a search engine should list. */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function DesktopLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AccountLocale />
      <AccountAppearance />
      <DiagnosticsPresence />
      {children}
    </>
  );
}
