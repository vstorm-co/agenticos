"use client";

import { useState } from "react";
import { BookOpen } from "lucide-react";
import { useTranslations } from "next-intl";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { CopyCode } from "@/components/settings/copy-code";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { DOCS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { MCP_CLIENT_NAME, MCP_CLIENTS, mcpSnippet, type McpAuth } from "./mcp-snippets";

/**
 * How to point Claude Code, Codex or any MCP client at this deployment's own MCP
 * server: the address, the way the client signs in, and the command or config
 * each client takes.
 */
export function McpConnect() {
  const t = useTranslations("mcpConnect");
  const { apiUrl } = usePublicConfig();
  const [auth, setAuth] = useState<McpAuth>("browser");
  const url = `${apiUrl}/mcp`;

  return (
    <section className="border-border bg-card rounded-xl border" data-tour="mcp-connect">
      <header className="border-border border-b px-5 py-4">
        <h2 className="text-foreground text-sm font-semibold">{t("title")}</h2>
        <p className="text-muted-foreground mt-1 text-xs">{t("why")}</p>
        <a
          href={DOCS.MCP_SERVER}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground mt-2 inline-flex items-center gap-1 text-xs underline underline-offset-2"
        >
          <BookOpen className="h-3.5 w-3.5" aria-hidden />
          {t("docs")}
        </a>
      </header>
      <div className="space-y-5 px-5 py-5">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <h3 className="text-xs font-semibold">{t("serverUrl")}</h3>
            <CopyCode code={url} />
          </div>
          <div className="space-y-1.5">
            <h3 className="text-xs font-semibold" id="mcp-auth">
              {t("signIn")}
            </h3>
            <div
              role="radiogroup"
              aria-labelledby="mcp-auth"
              className="bg-muted inline-flex rounded-lg p-0.5"
            >
              {(["browser", "key"] as const).map((choice) => (
                <button
                  key={choice}
                  type="button"
                  role="radio"
                  aria-checked={auth === choice}
                  onClick={() => setAuth(choice)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium",
                    auth === choice ? "bg-background shadow-sm" : "text-muted-foreground",
                  )}
                >
                  {t(choice === "browser" ? "viaBrowser" : "viaKey")}
                </button>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">
              {t(auth === "browser" ? "browserHint" : "keyHint")}
            </p>
          </div>
        </div>
        <Tabs defaultValue="claude-code">
          <TabsList>
            {MCP_CLIENTS.map((client) => (
              <TabsTrigger key={client} value={client}>
                {MCP_CLIENT_NAME[client]}
              </TabsTrigger>
            ))}
          </TabsList>
          {MCP_CLIENTS.map((client) => {
            const snippet = mcpSnippet(client, auth, url);
            return (
              <TabsContent key={client} value={client} className="space-y-2 pt-2">
                <p className="text-muted-foreground text-xs">{t(`note.${client}.${auth}`)}</p>
                {snippet && <CopyCode code={snippet} />}
              </TabsContent>
            );
          })}
        </Tabs>
      </div>
    </section>
  );
}
