"use client";

import { useTranslations } from "next-intl";
import { BROWSER_PROFILE_FIELDS } from "@/types/browser-credentials";
import type { BrowserSecretMetadata } from "@/types/secrets";

const fields = ["username", "password", "totp", ...BROWSER_PROFILE_FIELDS] as const;

export function BrowserCredentialMetadata({
  metadata,
}: {
  metadata?: BrowserSecretMetadata | null;
}) {
  const t = useTranslations("browserCredentials");
  if (!metadata) return <p className="text-muted-foreground text-xs">{t("metadataUnavailable")}</p>;
  return (
    <div className="text-muted-foreground space-y-1 text-xs">
      <p className="break-words">{metadata.allowed_origins.join(", ")}</p>
      <p>
        {fields
          .filter((field) => metadata.available_fields.includes(field))
          .map((field) => t(`fields.${field}`))
          .join(", ")}
      </p>
      {metadata.has_totp && <p>{t("includesTotp")}</p>}
    </div>
  );
}
