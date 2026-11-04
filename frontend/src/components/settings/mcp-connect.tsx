"use client";

import { useState, type ComponentType } from "react";
import { BookOpen, Code2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { brandMark } from "@/components/icons/brand-icon";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { CopyCode } from "@/components/settings/copy-code";
import { ContextHelp } from "@/components/ui/context-help";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { DOCS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import {
  MCP_CLIENT_NAME,
  MCP_CLIENTS,
  mcpSnippet,
  type McpAuth,
  type McpClient,
} from "./mcp-snippets";

/**
 * Each client's own mark. VS Code has none in the generated set - Simple Icons
 * dropped it - so it wears the generic code glyph rather than a hand-drawn logo.
 */
const CLIENT_ICON: Record<McpClient, ComponentType<{ className?: string }>> = {
  "claude-code": brandMark("claudecode"),
  codex: brandMark("codex"),
  "claude-desktop": brandMark("claude"),
  cursor: brandMark("cursor"),
  vscode: Code2,
};

/**
 * How to point Claude Code, Codex or any MCP client at this deployment's own MCP
 * server: the address, the way the client signs in, and the command or config
 * each client takes.
 */
export function McpConnect() {
  const t = useTranslations("mcpConnect");
  const { apiUrl } = usePublicConfig();
  const [auth, setAuth] = useState<McpAuth>("browser");
  const [client, setClient] = useState<McpClient>("claude-code");
  const chooseClient = (value: string): void => {
    const next = MCP_CLIENTS.find((candidate) => candidate === value);
    if (next) setClient(next);
  };
  const url = `${apiUrl}/mcp`;

  return (
    <section className="border-border bg-card rounded-xl border" data-tour="mcp-connect">
      <header className="border-border border-b px-5 py-4">
        <div className="flex items-center gap-1">
          <h2 className="text-foreground text-sm font-semibold">{t("title")}</h2>
          <ContextHelp>{t("why")}</ContextHelp>
        </div>
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
                    "touch:min-h-11 touch-manipulation rounded-md px-3 py-1.5 text-xs font-medium",
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
        <Tabs value={client} onValueChange={chooseClient}>
          <div className="md:hidden">
            <Select value={client} onValueChange={chooseClient}>
              <SelectTrigger aria-label={t("client")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MCP_CLIENTS.map((choice) => {
                  const Icon = CLIENT_ICON[choice];
                  return (
                    <SelectItem key={choice} value={choice}>
                      <span className="flex items-center gap-2">
                        <Icon className="size-4" aria-hidden />
                        {MCP_CLIENT_NAME[choice]}
                      </span>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>
          <TabsList className="hidden md:flex">
            {MCP_CLIENTS.map((client) => {
              const Icon = CLIENT_ICON[client];
              return (
                <TabsTrigger key={client} value={client}>
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  {MCP_CLIENT_NAME[client]}
                </TabsTrigger>
              );
            })}
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
