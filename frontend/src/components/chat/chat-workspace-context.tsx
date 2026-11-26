"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { CHAT_PANEL_INITIAL_WIDTH } from "./chat-panel-resize";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";

export type WorkspacePanel = "visuals" | "browser" | "files";
type Selection = { id: string } | null;

interface Workspace {
  id: string;
  shared: boolean;
  activePanel: WorkspacePanel | null;
  openPanel: (panel: WorkspacePanel) => void;
  close: () => void;
  browserId: string | null;
  fullscreen: boolean;
  setFullscreen: (fullscreen: boolean) => void;
  selection: Selection;
  showVisual: (id: string, fullscreen: boolean) => void;
  release: (id: string) => void;
  slot: HTMLElement | null;
  setSlot: (slot: HTMLElement | null) => void;
  width: number;
  setWidth: (width: number) => void;
}

const Context = createContext<Workspace | null>(null);

/** Scope the selected visual to this conversation, including embedded chats. */
export function ChatWorkspaceProvider({
  children,
  conversationId = null,
  shared = false,
}: {
  children: ReactNode;
  conversationId?: string | null;
  shared?: boolean;
}) {
  const id = useId();
  const [selection, setSelection] = useState<Selection>(null);
  const browserId = useBrowserPanelStore((state) => state.openCallId);
  const browserRequest = useBrowserPanelStore((state) => state.openRequest);
  const automaticBrowser = useBrowserPanelStore((state) => state.automatic);
  const closeBrowser = useBrowserPanelStore((state) => state.close);
  const browserConversation = useRef(conversationId);
  useLayoutEffect(() => {
    const previous = browserConversation.current;
    browserConversation.current = conversationId;
    // Reset before the new conversation's auto-open effects inspect the store.
    // A draft receiving its first id still owns the same browser.
    if (previous !== null && previous !== conversationId) closeBrowser();
  }, [conversationId, closeBrowser]);
  const sourcesOpen = useSourcesPanelStore((state) => state.isOpen);
  const closeSources = useSourcesPanelStore((state) => state.close);
  const [activePanel, setActivePanel] = useState<WorkspacePanel | null>(
    browserId ? "browser" : null,
  );
  const [fullscreen, setFullscreen] = useState(false);
  const close = useCallback(() => setActivePanel(null), []);
  const openPanel = useCallback(
    (panel: WorkspacePanel) => {
      closeSources();
      setActivePanel(panel);
    },
    [closeSources],
  );
  const showVisual = useCallback(
    (id: string, expanded: boolean) => {
      closeSources();
      setSelection({ id });
      setFullscreen(expanded);
      setActivePanel("visuals");
    },
    [closeSources],
  );
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const release = useCallback((id: string) => {
    setSelection((current) => (current?.id === id ? null : current));
  }, []);
  const [width, setWidth] = useState(CHAT_PANEL_INITIAL_WIDTH);
  const [previousBrowserRequest, setPreviousBrowserRequest] = useState(browserRequest);
  const [previousSources, setPreviousSources] = useState(sourcesOpen);
  const [previousConversation, setPreviousConversation] = useState(conversationId);
  if (previousBrowserRequest !== browserRequest) {
    setPreviousBrowserRequest(browserRequest);
    if (browserId !== null && (!automaticBrowser || (activePanel === null && !sourcesOpen)))
      setActivePanel("browser");
  }
  if (activePanel === "browser" && browserId === null) setActivePanel(null);
  if (activePanel === "visuals" && selection === null) setActivePanel(null);
  if (previousSources !== sourcesOpen) {
    setPreviousSources(sourcesOpen);
    if (sourcesOpen) setActivePanel(null);
  }
  if (previousConversation !== conversationId) {
    setPreviousConversation(conversationId);
    if (previousConversation !== null) {
      setSelection(null);
      setActivePanel(null);
      setFullscreen(false);
    }
  }
  useEffect(() => {
    if (activePanel !== null) closeSources();
  }, [activePanel, closeSources]);
  return (
    <Context.Provider
      value={{
        id,
        shared,
        activePanel,
        openPanel,
        close,
        browserId,
        fullscreen,
        setFullscreen,
        selection,
        showVisual,
        release,
        slot,
        setSlot,
        width,
        setWidth,
      }}
    >
      {children}
    </Context.Provider>
  );
}

/** Standalone/shared transcripts still get a workspace when no chat layout hosts one. */
export function ChatWorkspaceBoundary({
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
    <ChatWorkspaceProvider conversationId={conversationId}>{children}</ChatWorkspaceProvider>
  );
}

export function useVisualWorkspace(id: string) {
  const workspace = useRequiredChatWorkspace();
  const { release } = workspace;
  useEffect(() => () => release(id), [release, id]);
  return {
    ...workspace,
    open: workspace.activePanel === "visuals" && workspace.selection?.id === id,
    fullscreen: workspace.fullscreen,
    show: (fullscreen = false) => workspace.showVisual(id, fullscreen),
  };
}

export function useChatWorkspace() {
  return useContext(Context);
}

export function useRequiredChatWorkspace() {
  const workspace = useChatWorkspace();
  // i18n-exempt: invalid component composition is a programmer error
  if (workspace === null) throw new Error("A workspace requires ChatWorkspaceProvider");
  return workspace;
}

/** Reserve room beside the whole chat, including its composer, on wide layouts. */
export function VisualWorkspaceSlot() {
  const workspace = useContext(Context);
  const setSlot = workspace?.setSlot;
  const ref = useCallback((node: HTMLDivElement | null) => setSlot?.(node), [setSlot]);
  if (!workspace?.selection || workspace.activePanel !== "visuals" || workspace.fullscreen)
    return null;
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
