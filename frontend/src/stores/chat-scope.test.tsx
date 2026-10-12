import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatScope } from "./chat-scope";
import { useInChatScope } from "./chat-scope-context";
import { useAgentSelectionStore } from "./agent-selection-store";
import { useBrowserPanelStore } from "./browser-panel-store";
import { useChatStore } from "./chat-store";
import { useConversationStore } from "./conversation-store";
import { useFilePreviewStore } from "./file-preview-store";
import { useSourcesPanelStore } from "./sources-panel-store";

/** What one conversation sees, and a way to write to the store it reads. */
function Probe({
  name,
  onApi,
}: {
  name: string;
  onApi?: (api: ReturnType<typeof useChatStore.useApi>) => void;
}) {
  const count = useChatStore((state) => state.messages.length);
  const conversation = useConversationStore((state) => state.currentConversationId);
  const agent = useAgentSelectionStore((state) => state.selectedAgentId);
  const previewing = useFilePreviewStore((state) => state.openId);
  const browsing = useBrowserPanelStore((state) => state.openCallId);
  const sources = useSourcesPanelStore((state) => state.isOpen);
  const scoped = useInChatScope();
  onApi?.(useChatStore.useApi());
  return (
    <p data-testid={name}>
      {[count, conversation, agent, previewing, browsing, String(sources), String(scoped)].join(
        " ",
      )}
    </p>
  );
}

afterEach(() => {
  useChatStore.setState({ messages: [] });
  useConversationStore.getState().reset();
});

describe("a chat scope", () => {
  it("keeps its conversation apart from the console's and from another scope's", () => {
    let architect: ReturnType<typeof useChatStore.useApi> | null = null;
    render(
      <>
        <Probe name="console" />
        <ChatScope agentId="architect">
          <Probe name="window" onApi={(api) => (architect = api)} />
        </ChatScope>
        <ChatScope agentId="draft">
          <Probe name="panel" />
        </ChatScope>
      </>,
    );

    act(() => {
      architect!.getState().addMessage({
        id: "m1",
        role: "user",
        content: "hi",
        timestamp: new Date(),
      });
      useConversationStore.getState().setCurrentConversationId("main-thread");
    });

    expect(screen.getByTestId("console")).toHaveTextContent(/^0 main-thread\s+false false$/);
    expect(screen.getByTestId("window")).toHaveTextContent(/^1 architect\s+false true$/);
    expect(screen.getByTestId("panel")).toHaveTextContent(/^0 draft\s+false true$/);
    // The hook's own API is still the console's, for code that only acts on it.
    expect(useChatStore.getState().messages).toEqual([]);
  });
});
