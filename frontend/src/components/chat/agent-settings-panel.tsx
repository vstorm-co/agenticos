"use client";

import { useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, Settings2, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { RemoteChangeBanner } from "@/components/live-updates/remote-change-banner";
import { useChatAgentSettings } from "@/hooks/use-chat-agent-settings";
import { BrowserPanelFrame } from "./browser-panel-frame";
import { ChatAgentSettingsFields } from "./agent-settings-fields";
import { ChatAgentSettingsPublish } from "./agent-settings-publish";

interface SettingsPanelProps {
  panelId?: string;
  agentId: string;
  open: boolean;
  readOnly: boolean;
  onClose: () => void;
}

/** Lazily load the agent, then preserve its local edits while other panes are open. */
export function ChatAgentSettingsPanel(props: SettingsPanelProps) {
  const [visited, setVisited] = useState(false);
  if (props.open && !visited) setVisited(true);
  if (!props.open && !visited) return null;
  return <SettingsEditor {...props} />;
}

function SettingsEditor({ panelId, agentId, open, readOnly, onClose }: SettingsPanelProps) {
  const t = useTranslations("chat.agentSettings");
  const workspace = useTranslations("chat.workspace");
  const common = useTranslations("common");
  const editor = useChatAgentSettings(agentId, readOnly);
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const dismiss = () => {
    onClose();
    if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
  };
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    closeButton.current?.focus();
    const panel = closeButton.current?.closest<HTMLElement>("[data-browser-panel]");
    const keydown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        (event.target instanceof HTMLElement &&
          event.target.closest('[role="dialog"], [role="menu"], [role="listbox"]'))
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
      if (opener.current instanceof HTMLElement && opener.current.isConnected)
        opener.current.focus();
    };
    panel?.addEventListener("keydown", keydown);
    return () => {
      panel?.removeEventListener("keydown", keydown);
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <BrowserPanelFrame
      id={panelId}
      label={t("title")}
      resizeLabel={workspace("resize")}
      initialWidth={35}
    >
      {({ fullscreen, toggleFullscreen }) => (
        <>
          <header className="border-border flex shrink-0 items-center gap-2 border-b px-4 py-3">
            <Settings2 className="text-muted-foreground size-4" aria-hidden />
            <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{t("title")}</h2>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={toggleFullscreen}
              aria-label={t(fullscreen ? "restore" : "expand")}
            >
              {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </Button>
            <Button
              ref={closeButton}
              type="button"
              variant="ghost"
              size="icon"
              onClick={dismiss}
              aria-label={t("close")}
            >
              <X className="size-4" aria-hidden />
            </Button>
          </header>
          <div className="min-h-0 flex-1 scrollbar-thin space-y-4 overflow-y-auto overscroll-contain p-5">
            {editor.isLoading && (
              <p role="status" className="text-muted-foreground text-sm">
                {t("loading")}
              </p>
            )}
            {editor.error && (
              <div role="alert" className="space-y-2 text-sm">
                <p>{t("loadFailed")}</p>
                <Button variant="outline" size="sm" onClick={() => void editor.refetch()}>
                  {common("retry")}
                </Button>
              </div>
            )}
            {editor.agent && editor.spec && (
              <>
                <p className="text-muted-foreground text-xs leading-relaxed">{t("draftHint")}</p>
                {editor.remote.conflict && (
                  <RemoteChangeBanner
                    change={editor.remote.conflict}
                    onReload={editor.remote.reload}
                    onKeepMine={editor.remote.keepMine}
                  />
                )}
                {editor.editable ? (
                  <ChatAgentSettingsFields
                    spec={editor.spec}
                    disabled={editor.saveDraft.isPending}
                    update={editor.update}
                  />
                ) : (
                  <div className="space-y-3 text-sm">
                    <p role="status" className="text-muted-foreground">
                      {t(editor.agent.workflow_id ? "workflowOwned" : "readOnly")}
                    </p>
                    <h3 className="font-medium">{editor.spec.name}</h3>
                    <p className="text-muted-foreground whitespace-pre-wrap">
                      {editor.spec.description}
                    </p>
                    <h4 className="font-medium">{t("instructions")}</h4>
                    <p className="whitespace-pre-wrap">{editor.spec.instructions}</p>
                  </div>
                )}
                <Link
                  href={`/agents/${agentId}`}
                  className="text-muted-foreground block border-t pt-4 text-xs underline underline-offset-4"
                >
                  {t("openBuilder")}
                </Link>
              </>
            )}
          </div>
          {editor.editable && (
            <footer className="border-border flex shrink-0 flex-wrap items-center gap-2 border-t p-4">
              <p role="status" className="text-muted-foreground basis-full text-xs">
                {t(editor.saveDraft.isPending ? "saving" : editor.dirty ? "unsaved" : "saved")}
              </p>
              {editor.failure && (
                <p role="alert" className="text-destructive basis-full text-xs">
                  {editor.failure}
                </p>
              )}
              <Button
                type="button"
                size="sm"
                disabled={editor.blocked || !editor.dirty}
                onClick={() => void editor.save()}
              >
                {t("save")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={!editor.dirty || editor.saveDraft.isPending}
                onClick={editor.reset}
              >
                {t("reset")}
              </Button>
              {editor.agent?.can_publish && <ChatAgentSettingsPublish editor={editor} />}
            </footer>
          )}
        </>
      )}
    </BrowserPanelFrame>
  );
}
