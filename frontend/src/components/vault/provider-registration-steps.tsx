"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";

interface ProviderRegistrationStepsProps {
  provider: "google" | "microsoft" | "slack";
  redirectUri: string;
  consoleUrl: string;
  enableApisCommand?: string | null;
  mcp?: boolean;
}

/** Provider registration instructions shared by native accounts and MCP clients. */
export function ProviderRegistrationSteps({
  provider,
  redirectUri,
  consoleUrl,
  enableApisCommand,
  mcp = false,
}: ProviderRegistrationStepsProps) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  return (
    <div className="space-y-3">
      <div className="grid gap-2">
        <p className="text-sm font-medium">{t("redirect")}</p>
        <code className="rounded-md border p-2 text-xs break-all select-all">{redirectUri}</code>
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigator.clipboard.writeText(redirectUri)}
        >
          {t("copyRedirect")}
        </Button>
      </div>
      <p className="text-muted-foreground text-sm">
        {mcp
          ? { google: t("googleMcp"), microsoft: t("microsoftMcp"), slack: t("slackMcp") }[provider]
          : t(provider)}
      </p>
      <Button variant="outline" asChild>
        <a href={consoleUrl} target="_blank" rel="noopener noreferrer">
          {t("openConsole")}
        </a>
      </Button>
      {enableApisCommand && (
        <code className="bg-muted block rounded-md p-2 text-xs break-all select-all">
          {enableApisCommand}
        </code>
      )}
    </div>
  );
}
