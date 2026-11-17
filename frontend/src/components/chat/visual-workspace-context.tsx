"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { CHAT_PANEL_INITIAL_WIDTH } from "./chat-panel-resize";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

type Selection = { id: string; fullscreen: boolean } | null;

interface Workspace {
  selection: Selection;
  select: (selection: Selection) => void;
  release: (id: string) => void;
  slot: HTMLElement | null;
  setSlot: (slot: HTMLElement | null) => void;
  width: number;
  setWidth: (width: number) => void;
}

const Context = createContext<Workspace | null>(null);

/** Scope the selected visual to this conversation, including embedded chats. */
export function VisualWorkspaceProvider({
  children,
  conversationId = null,
}: {
  children: ReactNode;
  conversationId?: string | null;
}) {
  const [selection, setSelection] = useState<Selection>(null);
  const browserId = useBrowserPanelStore((state) => state.openCallId);
  const closeBrowser = useBrowserPanelStore((state) => state.close);
  const select = useCallback(
    (next: Selection) => {
      if (next !== null) closeBrowser();
      setSelection(next);
    },
    [closeBrowser],
  );
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const release = useCallback((id: string) => {
    setSelection((current) => (current?.id === id ? null : current));
  }, []);
  const [width, setWidth] = useState(CHAT_PANEL_INITIAL_WIDTH);
  const [previousConversation, setPreviousConversation] = useState(conversationId);
  if (browserId !== null && selection !== null) setSelection(null);
  if (previousConversation !== conversationId) {
    setPreviousConversation(conversationId);
    if (previousConversation !== null) setSelection(null);
  }
  return (
    <Context.Provider value={{ selection, select, release, slot, setSlot, width, setWidth }}>
      {children}
    </Context.Provider>
  );
}

/** Standalone/shared transcripts still get a workspace when no chat layout hosts one. */
export function VisualWorkspaceBoundary({
  children,
  conversationId,
}: {
  children: ReactNode;
  conversationId?: string | null;
}) {
  const workspace = useContext(Context);
  return workspace ? (
    children
  ) : (
    <VisualWorkspaceProvider conversationId={conversationId}>{children}</VisualWorkspaceProvider>
  );
}

export function useVisualWorkspace(id: string) {
  const workspace = useContext(Context);
  // i18n-exempt: invalid component composition is a programmer error
  if (workspace === null) throw new Error("A visual requires VisualWorkspaceProvider");
  const { select, release } = workspace;
  const close = useCallback(() => select(null), [select]);
  useEffect(() => () => release(id), [release, id]);
  return {
    ...workspace,
    open: workspace.selection?.id === id,
    fullscreen: workspace.selection?.id === id && workspace.selection.fullscreen,
    show: (fullscreen = false) => select({ id, fullscreen }),
    close,
  };
}

/** Reserve room beside the whole chat, including its composer, on wide layouts. */
export function VisualWorkspaceSlot() {
  const workspace = useContext(Context);
  const setSlot = workspace?.setSlot;
  const ref = useCallback((node: HTMLDivElement | null) => setSlot?.(node), [setSlot]);
  if (!workspace?.selection || workspace.selection.fullscreen) return null;
  return (
    <div
      ref={ref}
      data-visual-workspace-slot
      aria-hidden
      style={{ width: `${workspace.width}%` }}
      className="hidden h-full min-w-0 shrink-0 @min-[1000px]/visual-layout:block"
    />
  );
}
