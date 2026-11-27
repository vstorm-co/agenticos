import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import { ChatScope } from "@/stores/chat-scope";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useChatPanelStore } from "@/stores/chat-panel-store";
import { useSidebarStore } from "@/stores/sidebar-store";
import { ChatWorkspaceProvider, useRequiredChatWorkspace } from "./chat-workspace-context";
import { ChatWorkspaceFrame } from "./chat-workspace-frame";
import { MainChatContext } from "./main-chat-context";
function Controls() {
  const workspace = useRequiredChatWorkspace();
  return (
    <>
      <button onClick={() => workspace.openEnvironment("browser")}>Open Browser</button>
      <button onClick={workspace.close}>Close Browser</button>
      <button onClick={() => workspace.setFullscreen(true)}>Expand Browser</button>
      <ChatWorkspaceFrame environment>{() => <span>Browser content</span>}</ChatWorkspaceFrame>
    </>
  );
}
beforeEach(() => {
  useBrowserPanelStore.setState({ openCallId: null });
  useChatPanelStore.setState({ browserOpen: false });
});
it("reports main Browser visibility until close or unmount without changing primary navigation", async () => {
  const navBefore = useSidebarStore.getState().isCollapsed;
  const view = render(
    <MainChatContext.Provider value={true}>
      <ChatWorkspaceProvider shared>
        <Controls />
      </ChatWorkspaceProvider>
    </MainChatContext.Provider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
  expect(useChatPanelStore.getState().browserOpen).toBe(true);
  expect(useSidebarStore.getState().isCollapsed).toBe(navBefore);
  await userEvent.click(screen.getByRole("button", { name: "Close Browser" }));
  expect(useChatPanelStore.getState().browserOpen).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
  view.unmount();
  expect(useChatPanelStore.getState().browserOpen).toBe(false);
});
it("does not let embedded or standalone workspaces reset the main layout signal", async () => {
  act(() => useChatPanelStore.getState().setBrowserOpen(true));
  const embedded = render(
    <MainChatContext.Provider value={true}>
      <ChatScope agentId={null}>
        <ChatWorkspaceProvider shared>
          <Controls />
        </ChatWorkspaceProvider>
      </ChatScope>
    </MainChatContext.Provider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
  await userEvent.click(screen.getByRole("button", { name: "Close Browser" }));
  embedded.unmount();
  expect(useChatPanelStore.getState().browserOpen).toBe(true);
  const standalone = render(
    <ChatWorkspaceProvider>
      <Controls />
    </ChatWorkspaceProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
  standalone.unmount();
  expect(useChatPanelStore.getState().browserOpen).toBe(true);
});
it("contains narrow desktop panels while retaining phone and explicit fullscreen", async () => {
  render(
    <MainChatContext.Provider value={true}>
      <ChatWorkspaceProvider shared>
        <Controls />
      </ChatWorkspaceProvider>
    </MainChatContext.Provider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
  const panel = screen.getByRole("tabpanel", { name: "Browser" });
  expect(panel).toHaveClass("fixed", "md:absolute", "@min-[1000px]/browser-layout:relative");
  await userEvent.click(screen.getByRole("button", { name: "Expand Browser" }));
  expect(panel).toHaveClass("fixed");
  expect(panel).not.toHaveClass("md:absolute");
});

it("keeps the layout choice stable when later legacy browser frames select a page", () => {
  render(
    <MainChatContext.Provider value={true}>
      <ChatWorkspaceProvider shared>
        <Controls />
      </ChatWorkspaceProvider>
    </MainChatContext.Provider>,
  );
  act(() => useBrowserPanelStore.getState().open("call-one", true));
  expect(useChatPanelStore.getState().browserOpen).toBe(true);
  const transitions: boolean[] = [];
  const unsubscribe = useChatPanelStore.subscribe((state, previous) => {
    if (state.browserOpen !== previous.browserOpen) transitions.push(state.browserOpen);
  });
  try {
    act(() => useBrowserPanelStore.getState().open("call-two", true));
    expect(useChatPanelStore.getState().browserOpen).toBe(true);
    expect(transitions).toEqual([]);
  } finally {
    unsubscribe();
  }
});
