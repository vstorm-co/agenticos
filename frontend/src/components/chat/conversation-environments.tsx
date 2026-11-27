"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FolderOpen, Globe, Monitor } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui";
import { useConversationEnvironments } from "@/hooks/use-conversation-environments";
import type { EnvironmentExecutionTarget } from "@/lib/conversation-environments-api";
import { useRequiredChatWorkspace, type WorkspaceEnvironment } from "./chat-workspace-context";
import { ChatWorkspaceFrame } from "./chat-workspace-frame";
import { ConversationEnvironmentView } from "./conversation-environment-view";

interface Props {
  conversationId: string | null;
  agentId: string;
  panels: readonly WorkspaceEnvironment[];
  target: EnvironmentExecutionTarget;
  buttonSlot: HTMLElement | null;
  prepareConversation: () => Promise<string | null>;
  preparing: boolean;
}

/** The workspace menu opens views; provisioning requires the view's explicit Start. */
export function ConversationEnvironments({
  conversationId,
  agentId,
  panels,
  target,
  buttonSlot,
  prepareConversation,
  preparing,
}: Props) {
  const t = useTranslations("chat.workspace");
  const status = useTranslations("chat.environmentView");
  const common = useTranslations("common");
  const workspace = useRequiredChatWorkspace();
  const trigger = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const selected = workspace.environment;
  const visible =
    selected !== null && workspace.activePanel === selected && panels.includes(selected);
  const browserActive =
    workspace.browserId !== null &&
    workspace.activePanel === "browser" &&
    panels.includes("browser");
  const environments = useConversationEnvironments(
    conversationId,
    agentId,
    menuOpen || visible || browserActive,
    target,
  );
  const { refresh } = environments;
  const selectOwnedBrowser = useEffectEvent(() => {
    if (workspace.activePanel === "browser" && workspace.environment === null)
      workspace.openEnvironment("browser");
  });
  useEffect(() => {
    if (!browserActive || conversationId === null) return;
    let current = true;
    void refresh().then((result) => {
      if (result === null) return;
      const owned = result.data?.items.find((item) => item.kind === "browser");
      if (
        current &&
        !result.error &&
        owned !== undefined &&
        owned.id !== null &&
        (owned.state === "ready" || owned.state === "starting")
      )
        selectOwnedBrowser();
    });
    return () => {
      current = false;
    };
  }, [browserActive, conversationId, agentId, target, workspace.browserId, refresh]);

  async function open(kind: WorkspaceEnvironment) {
    setFailed(false);
    workspace.openEnvironment(kind, trigger.current);
    try {
      if ((await prepareConversation()) === null) setFailed(true);
    } catch {
      setFailed(true);
    }
  }

  const environment = environments.items?.find((item) => item.kind === selected);
  return (
    <>
      {buttonSlot &&
        createPortal(
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <span data-tour="chat-environments" className="inline-flex">
              <DropdownMenuTrigger asChild>
                <Button
                  ref={trigger}
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("open")}
                  title={t("open")}
                  data-tour="chat-workspace-open"
                  className="touch:size-11 size-8 shrink-0"
                >
                  <FolderOpen className="size-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
            </span>
            <DropdownMenuContent
              align="start"
              onCloseAutoFocus={(event) => {
                if (visible) event.preventDefault();
              }}
            >
              <DropdownMenuItem
                disabled={conversationId === null || preparing}
                onSelect={() => {
                  workspace.openPanel("files", trigger.current);
                }}
              >
                <FolderOpen className="size-4" aria-hidden />
                {t("files")}
              </DropdownMenuItem>
              {panels.map((kind) => (
                <DropdownMenuItem key={kind} disabled={preparing} onSelect={() => void open(kind)}>
                  {kind === "browser" ? (
                    <Globe className="size-4" aria-hidden />
                  ) : (
                    <Monitor className="size-4" aria-hidden />
                  )}
                  {t(kind)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>,
          buttonSlot,
        )}
      {selected !== null && panels.includes(selected) && (
        <ChatWorkspaceFrame panel={selected} environment>
          {() =>
            visible &&
            (failed || environments.error ? (
              <div role="alert" className="space-y-3 p-4 text-sm">
                <p>{status("loadFailed")}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setFailed(false);
                    if (conversationId === null) void open(selected);
                    else void environments.refresh();
                  }}
                >
                  {common("retry")}
                </Button>
              </div>
            ) : environment && conversationId !== null ? (
              <ConversationEnvironmentView
                conversationId={conversationId}
                environment={environment}
                visible
                onState={environments.remember}
                onStart={async () => {
                  await environments.start({
                    conversation: conversationId,
                    agent: agentId,
                    kind: selected,
                  });
                }}
                onEnd={() =>
                  environments.end({ conversation: conversationId, agent: agentId, kind: selected })
                }
                onRefresh={() => void environments.refresh()}
                isStarting={environments.isStarting}
                isEnding={environments.isEnding}
              />
            ) : (
              <div role="status" className="text-muted-foreground p-4 text-sm">
                {status("loading")}
              </div>
            ))
          }
        </ChatWorkspaceFrame>
      )}
    </>
  );
}
