import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { ConsoleToaster } from "@/components/ui/console-toaster";
import { visualToastOptions } from "./visual-actions";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { VisualDownload } from "./visual-download";
import { VisualFrame } from "./visual-frame";
import { VisualWorkspace } from "./visual-workspace";
import { ChatWorkspaceFrame } from "./chat-workspace-frame";
import { ChatWorkspaceTabs } from "./chat-workspace-tabs";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import {
  ChatWorkspaceBoundary,
  ChatWorkspaceProvider,
  VisualWorkspaceSlot,
  useVisualWorkspace,
  useRequiredChatWorkspace,
} from "./chat-workspace-context";

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect/></svg>';
const showPopover = vi.fn();
const hidePopover = vi.fn();
let wide = true;

function Example({ id = "one" }: { id?: string }) {
  const workspace = useVisualWorkspace(id);
  const [code, setCode] = useState(false);
  const [saving, setSaving] = useState(false);
  return (
    <>
      <button onClick={() => workspace.show()}>Open {id}</button>
      <VisualWorkspace
        visualId={id}
        title={id}
        content={SVG}
        code={code}
        onCodeChange={setCode}
        actions={
          <>
            <VisualDownload title={id} kind="svg" content={SVG} />
            <button onClick={() => setSaving(true)}>Save</button>
          </>
        }
        dialogs={
          <Dialog open={saving} onOpenChange={setSaving}>
            <DialogContent aria-describedby={undefined}>
              <DialogTitle>Save drawing</DialogTitle>
            </DialogContent>
          </Dialog>
        }
      >
        <VisualFrame kind="svg" title={id} content={SVG} done height={300} fill={workspace.open} />
      </VisualWorkspace>
    </>
  );
}

function Harness({
  conversationId = "c1",
  two = false,
  visible = true,
  shared = false,
}: {
  conversationId?: string | null;
  two?: boolean;
  visible?: boolean;
  shared?: boolean;
}) {
  return (
    <ChatWorkspaceProvider shared={shared} conversationId={conversationId}>
      <div>
        {visible && (
          <ChatWorkspaceBoundary>
            <Example />
          </ChatWorkspaceBoundary>
        )}
        {two && <Example id="two" />}
        <VisualWorkspaceSlot />
        {shared && <SharedPanes />}
      </div>
    </ChatWorkspaceProvider>
  );
}

function SharedPanes() {
  const workspace = useRequiredChatWorkspace();
  return (
    <>
      <button onClick={() => workspace.openPanel("files")}>Open files</button>
      <button onClick={workspace.close}>Hide workspace</button>
      <ChatWorkspaceFrame>
        {() => <input aria-label="Browser state" defaultValue="initial page" />}
      </ChatWorkspaceFrame>
      <ChatWorkspaceFrame panel="files">
        {() => <input aria-label="File state" defaultValue="initial file" />}
      </ChatWorkspaceFrame>
    </>
  );
}

beforeEach(() => {
  wide = true;
  useSourcesPanelStore.getState().close();
  vi.clearAllMocks();
  useBrowserPanelStore.setState({ openCallId: null });
  vi.spyOn(HTMLElement.prototype, "showPopover").mockImplementation(showPopover);
  vi.spyOn(HTMLElement.prototype, "hidePopover").mockImplementation(hidePopover);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.hasAttribute("data-visual-workspace-slot"))
      return wide ? new DOMRect(600, 40, 660, 700) : new DOMRect();
    return new DOMRect(0, 40, 1260, 700);
  });
});
afterEach(() => {
  act(() => toast.dismiss());
  vi.restoreAllMocks();
});

// Popovers have no top-layer implementation in jsdom. The live browser check
// exercises showPopover/hidePopover with a script-backed calculator as well.
Object.defineProperty(HTMLElement.prototype, "showPopover", {
  configurable: true,
  value: () => {},
});
Object.defineProperty(HTMLElement.prototype, "hidePopover", {
  configurable: true,
  value: () => {},
});

describe("a visual workspace", () => {
  it("keeps success actions and error feedback inside the open workspace", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ConsoleToaster closeLabel="Close global toast" />
        <Harness />
      </>,
    );
    await user.click(screen.getByRole("button", { name: "Open one" }));
    const workspace = screen.getByRole("region", { name: "Visual: one" });
    const openApp = vi.fn();
    act(() => {
      toast.success("Saved visual", {
        ...visualToastOptions(),
        action: { label: "Open app", onClick: openApp },
      });
      toast.error("Failed visual", visualToastOptions());
    });
    expect(workspace).toContainElement(await screen.findByText("Saved visual"));
    expect(workspace).toContainElement(await screen.findByText("Failed visual"));
    await user.click(screen.getByRole("button", { name: "Open app" }));
    expect(openApp).toHaveBeenCalledOnce();
    expect(screen.getByRole("region", { name: "Visual: one" })).toBe(workspace);
  });

  it("only marks the open workspace as a popover while retaining the inline document", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const frame = screen.getByTitle("one");
    const inline = frame.closest("[data-visual-workspace]")!;
    expect(inline).not.toHaveAttribute("popover");

    await user.click(screen.getByRole("button", { name: "Open one" }));
    expect(inline).toHaveAttribute("popover", "manual");

    await user.click(screen.getByRole("button", { name: "Close visual" }));
    expect(inline).not.toHaveAttribute("popover");
    expect(screen.getByTitle("one")).toBe(frame);
    expect(inline).toBeVisible();
  });

  it("keeps one iframe and its browsing context through tabs, expansion, close and reopen", async () => {
    const user = userEvent.setup();
    const view = render(<Harness />);
    const frame = screen.getByTitle("one") as HTMLIFrameElement;
    const browsingContext = frame.contentWindow!;
    Reflect.set(browsingContext, "scenario", "keep this value");
    const trigger = screen.getByRole("button", { name: "Open one" });
    await user.click(trigger);
    const workspace = screen.getByRole("region", { name: "Visual: one" });
    expect(workspace).toHaveAttribute("data-visual-workspace", "docked");
    expect(workspace).toHaveStyle({ left: "600px", top: "40px", width: "660px", height: "700px" });
    await user.click(screen.getByRole("tab", { name: "Code" }));
    expect(screen.getByText(SVG, { selector: "pre" })).toBeVisible();
    expect(frame).not.toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(workspace).toHaveAttribute("data-visual-workspace", "fullscreen");
    expect(screen.queryByRole("separator")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Return to side panel" }));
    await user.click(screen.getByRole("button", { name: "Close visual" }));
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    expect(screen.getByTitle("one")).toBe(frame);
    expect(frame.contentWindow).toBe(browsingContext);
    expect(Reflect.get(frame.contentWindow!, "scenario")).toBe("keep this value");
    expect(showPopover).toHaveBeenCalledTimes(2);
    expect(hidePopover).not.toHaveBeenCalled();
    view.unmount();
    expect(hidePopover).toHaveBeenCalledTimes(1);
  });

  it("uses the full window in narrow chats and follows layout changes without a new frame", () => {
    wide = false;
    render(<Harness />);
    const frame = screen.getByTitle("one");
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    const workspace = screen.getByRole("region", { name: /^Visual:/ });
    expect(workspace).toHaveAttribute("data-visual-workspace", "fullscreen");
    expect(screen.queryByRole("separator")).toBeNull();
    wide = true;
    fireEvent.resize(window);
    expect(workspace).toHaveAttribute("data-visual-workspace", "docked");
    const boundary = screen.getByRole("separator", { name: "Resize visual panel" });
    fireEvent.keyDown(boundary, { key: "ArrowLeft" });
    expect(boundary).toHaveAttribute("aria-valuenow", "57");
    fireEvent.scroll(window);
    expect(screen.getByTitle("one")).toBe(frame);
    expect(showPopover).toHaveBeenCalledTimes(1);
  });

  it("resizes within the chat bounds with a pointer and retains the document", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const view = render(<Harness />);
    const frame = screen.getByTitle("one");
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    const boundary = screen.getByRole("separator");
    Object.defineProperty(boundary, "setPointerCapture", { value: vi.fn() });
    fireEvent.pointerDown(boundary, { button: 0 });
    fireEvent.pointerMove(boundary, { clientX: 504 });
    fireEvent.pointerUp(boundary);
    expect(boundary).toHaveAttribute("aria-valuenow", "60");
    expect(view.container.querySelector("[data-visual-workspace-slot]")).toHaveStyle({
      width: "60%",
    });
    expect(screen.getByTitle("one")).toBe(frame);
    vi.unstubAllGlobals();
  });

  it("keeps export menus and save dialogs in the workspace's top layer", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open one" }));
    const workspace = screen.getByRole("region", { name: /^Visual:/ });
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(workspace).toContainElement(screen.getByRole("menu"));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("region", { name: /^Visual:/ })).toBe(workspace);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(workspace).toContainElement(screen.getByRole("dialog"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("region", { name: /^Visual:/ })).toBe(workspace);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: /^Visual:/ })).toBeNull();
  });

  it("selects one visual at a time while retaining the previous document", async () => {
    const user = userEvent.setup();
    render(<Harness two />);
    const first = screen.getByTitle("one");
    await user.click(screen.getByRole("button", { name: "Open one" }));
    await user.click(screen.getByRole("button", { name: "Open two" }));
    expect(screen.getAllByRole("region", { name: /^Visual:/ })).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Visual: two" })).toBeInTheDocument();
    expect(screen.getByTitle("one")).toBe(first);
    expect(showPopover).toHaveBeenCalledTimes(2);
    expect(hidePopover).not.toHaveBeenCalled();
  });

  it("clears the workspace on conversation changes while keeping a newly named conversation", () => {
    const view = render(<Harness conversationId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    view.rerender(<Harness conversationId="created" />);
    expect(screen.getByRole("region", { name: /^Visual:/ })).toBeInTheDocument();
    view.rerender(<Harness conversationId="another" />);
    expect(screen.queryByRole("region", { name: /^Visual:/ })).toBeNull();
    expect(view.container.querySelector("[data-visual-workspace-slot]")).toBeNull();
  });

  it("shares the chat's side space with its live browser", () => {
    useBrowserPanelStore.setState({ openCallId: "browse" });
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(useBrowserPanelStore.getState().openCallId).toBe("browse");
    expect(screen.getByRole("region", { name: /^Visual:/ })).toBeInTheDocument();
    act(() => useBrowserPanelStore.getState().open("next-browse"));
    expect(screen.queryByRole("region", { name: /^Visual:/ })).toBeNull();
  });

  it("supports standalone transcripts with no docking slot", () => {
    render(
      <ChatWorkspaceBoundary>
        <Example />
      </ChatWorkspaceBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(screen.getByRole("region", { name: /^Visual:/ })).toHaveAttribute(
      "data-visual-workspace",
      "fullscreen",
    );
    expect(
      within(screen.getByRole("region", { name: /^Visual:/ })).getByRole("tab", {
        name: "Preview",
      }),
    ).toBeInTheDocument();
  });

  it("renders no reserved space without a workspace and rejects a missing provider", () => {
    const view = render(<VisualWorkspaceSlot />);
    expect(view.container).toBeEmptyDOMElement();
    expect(() => renderHook(() => useVisualWorkspace("missing"))).toThrow(
      "A workspace requires ChatWorkspaceProvider",
    );
  });

  it("releases side space when the selected drawing is removed", () => {
    const view = render(<Harness two />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(screen.getByRole("region", { name: /^Visual:/ })).toBeInTheDocument();
    view.rerender(<Harness two visible={false} />);
    expect(screen.queryByRole("region", { name: /^Visual:/ })).toBeNull();
    expect(view.container.querySelector("[data-visual-workspace-slot]")).toBeNull();
    expect(screen.getByTitle("two")).toBeInTheDocument();
  });

  it("returns inline for a modal opened elsewhere without replacing the live page", async () => {
    render(<Harness />);
    const frame = screen.getByTitle("one");
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "open");
    document.body.append(dialog);
    await waitFor(() => expect(screen.queryByRole("region", { name: /^Visual:/ })).toBeNull());
    expect(screen.getByTitle("one")).toBe(frame);
    dialog.remove();
  });
});

describe("shared workspace tabs", () => {
  it("retains the same visual, browser and file nodes across tabs, hiding and expansion", async () => {
    useBrowserPanelStore.getState().open("browse");
    render(<Harness shared />);
    const user = userEvent.setup();
    const browser = screen.getByRole("textbox", { name: "Browser state" });
    await user.type(browser, " kept");
    await user.click(screen.getByRole("tab", { name: "Files" }));
    const file = screen.getByRole("textbox", { name: "File state" });
    await user.type(file, " kept");
    await user.click(screen.getByRole("button", { name: "Open one" }));
    const frame = screen.getByTitle("one") as HTMLIFrameElement;
    const context = frame.contentWindow!;
    Reflect.set(context, "scenario", "retained");
    const visuals = screen.getByRole("tab", { name: "Visuals" });
    expect(visuals).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Visuals" })).toHaveAttribute(
      "id",
      visuals.getAttribute("aria-controls"),
    );
    await user.click(screen.getByRole("button", { name: "Full screen" }));
    await user.click(screen.getByRole("tab", { name: "Browser" }));
    expect(screen.getByRole("textbox", { name: "Browser state" })).toBe(browser);
    expect(browser).toHaveValue("initial page kept");
    expect(screen.getByRole("tabpanel", { name: "Browser" })).toHaveAttribute(
      "data-browser-panel",
      "fullscreen",
    );
    await user.click(screen.getByRole("tab", { name: "Files" }));
    expect(screen.getByRole("textbox", { name: "File state" })).toBe(file);
    expect(file).toHaveValue("initial file kept");
    expect(browser.closest("aside")).toHaveAttribute("inert");
    await user.click(screen.getByRole("button", { name: "Hide workspace" }));
    expect(screen.queryByRole("tabpanel", { name: /^(Visuals|Browser|Files)$/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open files" }));
    await user.click(screen.getByRole("tab", { name: "Visuals" }));
    expect(screen.getByTitle("one")).toBe(frame);
    expect(frame.contentWindow).toBe(context);
    expect(Reflect.get(context, "scenario")).toBe("retained");
    expect(useBrowserPanelStore.getState().openCallId).toBe("browse");
  });

  it("disables unavailable tabs and supports keyboard selection without losing focus", async () => {
    render(<Harness shared />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open files" }));
    expect(screen.getByRole("tab", { name: "Visuals" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Browser" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Open one" }));
    screen.getByRole("tab", { name: "Visuals" }).focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(screen.getByRole("tab", { name: "Files" })).toHaveFocus());
    await user.keyboard("{ArrowLeft}");
    await waitFor(() => expect(screen.getByRole("tab", { name: "Visuals" })).toHaveFocus());
    await user.keyboard("{End}");
    await waitFor(() => expect(screen.getByRole("tab", { name: "Files" })).toHaveFocus());
    await user.keyboard("{Home}");
    await waitFor(() => expect(screen.getByRole("tab", { name: "Visuals" })).toHaveFocus());
    await user.keyboard("x");
    expect(screen.getByRole("tab", { name: "Visuals" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens explicit browser requests but leaves the selected tab alone for automatic activity", () => {
    render(<Harness shared />);
    act(() => useBrowserPanelStore.getState().open("browse", true));
    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    act(() => useBrowserPanelStore.getState().open("next", true));
    expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute("aria-selected", "true");
    act(() => useBrowserPanelStore.getState().open("next"));
    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    act(() => useBrowserPanelStore.getState().close());
    expect(screen.queryByRole("tabpanel", { name: /^(Visuals|Browser|Files)$/ })).toBeNull();
  });

  it("coordinates sources and leaves them open for background browser activity", () => {
    render(<Harness shared />);
    const sources = () =>
      useSourcesPanelStore
        .getState()
        .open([{ index: 1, type: "web", title: "Source", url: "https://example.org" }]);
    fireEvent.click(screen.getByRole("button", { name: "Open files" }));
    act(sources);
    expect(screen.queryByRole("tabpanel", { name: /^(Visuals|Browser|Files)$/ })).toBeNull();
    act(() => useBrowserPanelStore.getState().open("browse", true));
    expect(useSourcesPanelStore.getState().isOpen).toBe(true);
    act(() => useBrowserPanelStore.getState().open("browse"));
    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
    act(sources);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(useSourcesPanelStore.getState().isOpen).toBe(false);
  });

  it("renders no shared tab strip outside its host", () => {
    const view = render(<ChatWorkspaceTabs panel="files" />);
    expect(view.container).toBeEmptyDOMElement();
  });
});
