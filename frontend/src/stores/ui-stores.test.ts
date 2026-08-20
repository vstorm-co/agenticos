import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatSidebarStore } from "./chat-sidebar-store";
import { useConversationStore } from "./conversation-store";
import { useFilePreviewStore } from "./file-preview-store";
import { useOrgStore } from "./org-store";
import { useSidebarStore } from "./sidebar-store";
import { useSourcesPanelStore } from "./sources-panel-store";
import { getResolvedTheme, useThemeStore } from "./theme-store";
import type { ChatMessageFile, ConversationMessage } from "@/types";

/**
 * The UI stores: what is open, what is selected, and which organization the
 * screen is showing.
 *
 * Most of it is a boolean with a name. Two are not, and both have a rule worth
 * pinning: the organization store remembers the selection across reloads but
 * deliberately forgets which organizations were refused, and the theme resolves
 * "system" against the browser rather than storing a guess.
 */
describe("the two sidebars", () => {
  it("opens, closes and toggles independently of each other", () => {
    // Two stores rather than one because the chat's own sidebar and the app's
    // navigation are open on the same screen at the same time.
    useSidebarStore.getState().open();
    expect(useSidebarStore.getState().isOpen).toBe(true);
    expect(useChatSidebarStore.getState().isOpen).toBe(false);

    useSidebarStore.getState().toggle();
    expect(useSidebarStore.getState().isOpen).toBe(false);

    useChatSidebarStore.getState().toggle();
    expect(useChatSidebarStore.getState().isOpen).toBe(true);

    useChatSidebarStore.getState().open();
    expect(useChatSidebarStore.getState().isOpen).toBe(true);

    useChatSidebarStore.getState().close();
    useSidebarStore.getState().close();
    expect(useChatSidebarStore.getState().isOpen).toBe(false);
    expect(useSidebarStore.getState().isOpen).toBe(false);
  });
});

describe("the file preview panel", () => {
  const file: ChatMessageFile = {
    id: "f-1",
    filename: "invoice.pdf",
    mime_type: "application/pdf",
    file_type: "pdf",
  };

  it("is closed until a file is opened into it, and closed again after", () => {
    // A null id is the closed state rather than a separate flag, so the dialog
    // cannot be open with nothing in it.
    useFilePreviewStore.getState().setAvailable([file]);
    expect(useFilePreviewStore.getState().openId).toBeNull();

    useFilePreviewStore.getState().open(file);
    expect(useFilePreviewStore.getState().openId).toBe(file.id);

    useFilePreviewStore.getState().close();
    expect(useFilePreviewStore.getState().openId).toBeNull();
  });

  it("pages within the conversation's files rather than the caller's", () => {
    // Where a file was clicked is not a fact about which other files exist. The
    // panel used to pass the conversation's list and a message its own, so the
    // same file paged from one surface and not from the other.
    const other = { ...file, id: "f-2", filename: "notes.txt" };
    useFilePreviewStore.getState().setAvailable([file, other]);

    useFilePreviewStore.getState().open(other);
    expect(useFilePreviewStore.getState().openId).toBe("f-2");

    useFilePreviewStore.getState().select(0);
    expect(useFilePreviewStore.getState().openId).toBe(file.id);
  });

  it("holds an index the set does not have rather than opening nothing", () => {
    useFilePreviewStore.getState().setAvailable([file]);
    useFilePreviewStore.getState().open(file);

    useFilePreviewStore.getState().select(4);

    expect(useFilePreviewStore.getState().openId).toBe(file.id);
  });

  it("opens a file the conversation does not carry, alone", () => {
    // A surface can hold one the transcript does not; refusing to show it would
    // be worse than showing it by itself.
    useFilePreviewStore.getState().setAvailable([{ ...file, id: "f-9" }]);

    useFilePreviewStore.getState().open(file);

    expect(useFilePreviewStore.getState().available).toEqual([file]);
    expect(useFilePreviewStore.getState().openId).toBe(file.id);
  });
});

describe("the sources panel", () => {
  const source = { index: 1, type: "rag" as const, title: "handbook.pdf" };

  it("opens on the citation that was clicked", () => {
    useSourcesPanelStore.getState().open([source], 1);

    expect(useSourcesPanelStore.getState()).toMatchObject({
      isOpen: true,
      sources: [source],
      highlightedIndex: 1,
    });
  });

  it("highlights nothing when the whole list was asked for", () => {
    // Opening the panel from the message footer rather than from a citation.
    useSourcesPanelStore.getState().open([source]);

    expect(useSourcesPanelStore.getState().highlightedIndex).toBeNull();
  });

  it("forgets the highlight on close but keeps the sources", () => {
    // Reopening for the same message must not re-highlight a citation nobody
    // clicked this time; the list itself is what the panel renders next.
    useSourcesPanelStore.getState().open([source], 1);

    useSourcesPanelStore.getState().close();

    expect(useSourcesPanelStore.getState()).toMatchObject({
      isOpen: false,
      highlightedIndex: null,
      sources: [source],
    });
  });
});

describe("the conversation selection", () => {
  const message = { id: "m-1", role: "user", content: "hi" } as ConversationMessage;

  beforeEach(() => useConversationStore.getState().reset());

  it("holds the selection, its messages and the state of the fetch", () => {
    useConversationStore.getState().setCurrentConversationId("c-1");
    useConversationStore.getState().setCurrentMessages([message]);
    useConversationStore.getState().setLoading(true);
    useConversationStore.getState().setError("Could not load");

    expect(useConversationStore.getState()).toMatchObject({
      currentConversationId: "c-1",
      currentMessages: [message],
      isLoading: true,
      error: "Could not load",
    });
  });

  it("appends a message to the loaded history", () => {
    useConversationStore.getState().setCurrentMessages([message]);

    useConversationStore.getState().addMessage({ ...message, id: "m-2" });

    expect(useConversationStore.getState().currentMessages.map((msg) => msg.id)).toEqual([
      "m-1",
      "m-2",
    ]);
  });

  it("appends to a history that was never loaded", () => {
    // A persisted store from an older build has no `currentMessages` at all, and
    // spreading `undefined` throws rather than starting a list.
    useConversationStore.setState({
      currentMessages: undefined as unknown as ConversationMessage[],
    });

    useConversationStore.getState().addMessage(message);

    expect(useConversationStore.getState().currentMessages).toEqual([message]);
  });

  it("resets everything at once, which is what switching conversations does", () => {
    // Leaving the previous conversation's messages behind renders them under the
    // new title while the fetch is in flight.
    useConversationStore.getState().setCurrentConversationId("c-1");
    useConversationStore.getState().setCurrentMessages([message]);
    useConversationStore.getState().setError("stale");

    useConversationStore.getState().reset();

    expect(useConversationStore.getState()).toMatchObject({
      currentConversationId: null,
      currentMessages: [],
      isLoading: false,
      error: null,
    });
  });
});

describe("the active organization", () => {
  beforeEach(() => useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] }));

  it("holds which organization the screen is showing", () => {
    useOrgStore.getState().setActiveOrgId("org-1");
    expect(useOrgStore.getState().activeOrgId).toBe("org-1");

    useOrgStore.getState().setActiveOrgId(null);
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("records an organization the server refused, once", () => {
    // The list is read by both "pick a default" and "recover from a refusal", so
    // a duplicate entry is how those two start handing the selection back and
    // forth.
    useOrgStore.getState().markOrgRefused("org-2");
    useOrgStore.getState().markOrgRefused("org-2");

    expect(useOrgStore.getState().refusedOrgIds).toEqual(["org-2"]);
  });

  it("keeps the refusals of this session in order", () => {
    useOrgStore.getState().markOrgRefused("org-2");
    useOrgStore.getState().markOrgRefused("org-3");

    expect(useOrgStore.getState().refusedOrgIds).toEqual(["org-2", "org-3"]);
  });

  it("persists the selection and never the refusals", () => {
    // A refusal is a fact about right now: re-adding the member has to be enough
    // to make the organization usable again, without anybody clearing storage.
    const persisted = useOrgStore.persist.getOptions().partialize?.({
      ...useOrgStore.getState(),
      activeOrgId: "org-1",
      refusedOrgIds: ["org-2"],
    }) as Record<string, unknown>;

    expect(persisted).toEqual({ activeOrgId: "org-1" });
  });
});

describe("the theme", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("starts on the system's preference", () => {
    expect(useThemeStore.getState().theme).toBe("system");
  });

  it("holds an explicit choice", () => {
    useThemeStore.getState().setTheme("dark");
    expect(useThemeStore.getState().theme).toBe("dark");

    useThemeStore.getState().setTheme("system");
  });

  it("resolves an explicit choice to itself", () => {
    expect(getResolvedTheme("dark")).toBe("dark");
    expect(getResolvedTheme("light")).toBe("light");
  });

  it("resolves 'system' to light where there is no browser to ask", () => {
    // Rendered on the server, where the class has to be decided before anything
    // knows the visitor's preference.
    vi.stubGlobal("window", undefined);

    expect(getResolvedTheme("system")).toBe("light");
  });

  it("resolves 'system' by asking the browser, every time", () => {
    // Not stored: somebody changing their OS theme with the tab open expects the
    // page to follow.
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    expect(getResolvedTheme("system")).toBe("dark");

    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
    expect(getResolvedTheme("system")).toBe("light");
  });
});
