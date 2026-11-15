"use client";

import { KeyRound, Plug } from "lucide-react";
import { useUrlState } from "@/hooks/use-url-state";
import { useTranslations } from "next-intl";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ApiKeysManager } from "./api-keys-manager";
import { ApiUsage } from "./api-usage";
import { McpConnect } from "./mcp-connect";
import { ConnectedApps } from "./connected-apps";

/** Both access methods remain addressable through their existing URLs. */
export function DeveloperAccess({ initial = "api" }: { initial?: "api" | "mcp" }) {
  const t = useTranslations("nav");
  const [section, setSection] = useUrlState("access");
  const selected = section === "api" || section === "mcp" ? section : initial;
  return (
    <Tabs
      value={selected}
      onValueChange={(value) => setSection(value === initial ? null : value)}
      className="flex min-h-0 flex-1 flex-col gap-4"
    >
      <TabsList aria-label={t("developerAccess")} className="w-fit">
        <TabsTrigger value="api">
          <KeyRound className="size-4" aria-hidden />
          {t("api")}
        </TabsTrigger>
        <TabsTrigger value="mcp">
          <Plug className="size-4" aria-hidden />
          {t("mcpClients")}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="api" className="flex min-h-0 flex-1 flex-col gap-4">
        <ApiUsage />
        <ApiKeysManager />
      </TabsContent>
      <TabsContent value="mcp" className="flex min-h-0 flex-1 flex-col gap-4">
        <McpConnect />
        <ConnectedApps />
      </TabsContent>
    </Tabs>
  );
}
