import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/** Keep the actual form layout while its controls wait for their saved values. */
export function LoadingForm({ loading, children }: { loading: boolean; children: ReactNode }) {
  const t = useTranslations("states");
  return (
    <div role={loading ? "status" : undefined} aria-label={loading ? t("loading") : undefined}>
      <div
        inert={loading}
        aria-hidden={loading || undefined}
        className={cn(
          loading && [
            "[&_p[id$=-desc]]:bg-muted [&_p[id$=-desc]]:animate-pulse [&_p[id$=-desc]]:text-transparent! [&_svg]:invisible",
            "[&_input]:bg-muted [&_input]:animate-pulse [&_input]:text-transparent [&_input::placeholder]:text-transparent",
            "[&_textarea]:bg-muted [&_textarea]:animate-pulse [&_textarea]:text-transparent [&_textarea::placeholder]:text-transparent",
            "[&_button]:bg-muted! [&_button]:animate-pulse [&_button]:text-transparent! [&_button>*]:invisible",
          ],
        )}
      >
        {children}
      </div>
    </div>
  );
}
