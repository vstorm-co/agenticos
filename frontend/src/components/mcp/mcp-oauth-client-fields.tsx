"use client";

import { useTranslations } from "next-intl";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { Input, Label } from "@/components/ui";

interface McpOAuthClientFieldsProps {
  clientId: string;
  clientSecret: string;
  onClientIdChange: (value: string) => void;
  onClientSecretChange: (value: string) => void;
}

/**
 * A client the person registered at the provider by hand, for a server that
 * will not register one itself.
 *
 * Most MCP servers register this app on the spot (RFC 7591), and both fields
 * stay empty. HubSpot's publishes no registration endpoint and hands out
 * credentials only for an "MCP auth app" created in the account - so without
 * these two fields the flow ended at "This server rejected the client
 * registration request" with nowhere to go. The redirect URL is shown because
 * the provider has to hold it exactly, and guessing it was the other half of
 * the dead end.
 */
export function McpOAuthClientFields({
  clientId,
  clientSecret,
  onClientIdChange,
  onClientSecretChange,
}: McpOAuthClientFieldsProps) {
  const t = useTranslations("mcp");
  // The backend builds the redirect from `FRONTEND_URL`, the deployment's
  // canonical console origin - which is what `PUBLIC_SITE_URL` configures on
  // this side. The browser's own origin can differ from it (a port-forward, an
  // internal hostname), and a redirect URL registered off that would never
  // match the one the flow sends.
  const { siteUrl } = usePublicConfig();
  const redirectUrl = `${siteUrl}/api/me/mcp-connections/oauth/callback`;

  return (
    <div className="space-y-3 rounded-md border border-dashed p-3">
      <div>
        <p className="text-sm font-medium">{t("oauthOwnClient")}</p>
        <p className="text-muted-foreground mt-1 text-xs">{t("oauthOwnClientHint")}</p>
      </div>
      <div>
        <Label>{t("oauthRedirectUrl")}</Label>
        <code className="bg-muted mt-1.5 block rounded px-2 py-1.5 font-mono text-xs break-all select-all">
          {redirectUrl}
        </code>
        <p className="text-foreground/45 mt-1 text-[11px]">{t("oauthRedirectUrlHint")}</p>
      </div>
      <div>
        <Label htmlFor="mcp-client-id">{t("oauthClientId")}</Label>
        <Input
          id="mcp-client-id"
          value={clientId}
          onChange={(event) => onClientIdChange(event.target.value)}
          maxLength={512}
          autoComplete="off"
          className="mt-1.5 font-mono text-sm"
        />
      </div>
      <div>
        <Label htmlFor="mcp-client-secret">{t("oauthClientSecret")}</Label>
        <Input
          id="mcp-client-secret"
          type="password"
          value={clientSecret}
          onChange={(event) => onClientSecretChange(event.target.value)}
          maxLength={4096}
          autoComplete="new-password"
          className="mt-1.5 font-mono text-sm"
        />
        <p className="text-foreground/45 mt-1 text-[11px]">{t("oauthClientSecretHint")}</p>
      </div>
    </div>
  );
}
