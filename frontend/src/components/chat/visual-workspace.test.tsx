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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { VisualDownload } from "./visual-download";
import { VisualFrame } from "./visual-frame";
import { VisualWorkspace } from "./visual-workspace";
import {
  VisualWorkspaceBoundary,
  VisualWorkspaceProvider,
  VisualWorkspaceSlot,
  useVisualWorkspace,
} from "./visual-workspace-context";

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
}: {
  conversationId?: string | null;
  two?: boolean;
  visible?: boolean;
}) {
  return (
    <VisualWorkspaceProvider conversationId={conversationId}>
      <div>
        {visible && (
          <VisualWorkspaceBoundary>
            <Example />
          </VisualWorkspaceBoundary>
        )}
        {two && <Example id="two" />}
        <VisualWorkspaceSlot />
      </div>
    </VisualWorkspaceProvider>
  );
}

beforeEach(() => {
  wide = true;
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
afterEach(() => vi.restoreAllMocks());

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
    expect(hidePopover).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(hidePopover).toHaveBeenCalledTimes(2);
  });

  it("uses the full window in narrow chats and follows layout changes without a new frame", () => {
    wide = false;
    render(<Harness />);
    const frame = screen.getByTitle("one");
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    const workspace = screen.getByRole("region");
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
    const workspace = screen.getByRole("region");
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(workspace).toContainElement(screen.getByRole("menu"));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("region")).toBe(workspace);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(workspace).toContainElement(screen.getByRole("dialog"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("region")).toBe(workspace);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("selects one visual at a time while retaining the previous document", async () => {
    const user = userEvent.setup();
    render(<Harness two />);
    const first = screen.getByTitle("one");
    await user.click(screen.getByRole("button", { name: "Open one" }));
    await user.click(screen.getByRole("button", { name: "Open two" }));
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Visual: two" })).toBeInTheDocument();
    expect(screen.getByTitle("one")).toBe(first);
    expect(showPopover).toHaveBeenCalledTimes(2);
    expect(hidePopover).toHaveBeenCalledTimes(1);
  });

  it("clears the workspace on conversation changes while keeping a newly named conversation", () => {
    const view = render(<Harness conversationId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    view.rerender(<Harness conversationId="created" />);
    expect(screen.getByRole("region")).toBeInTheDocument();
    view.rerender(<Harness conversationId="another" />);
    expect(screen.queryByRole("region")).toBeNull();
    expect(view.container.querySelector("[data-visual-workspace-slot]")).toBeNull();
  });

  it("shares the chat's side space with its live browser", () => {
    useBrowserPanelStore.setState({ openCallId: "browse" });
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
    expect(screen.getByRole("region")).toBeInTheDocument();
    act(() => useBrowserPanelStore.getState().open("next-browse"));
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("supports standalone transcripts with no docking slot", () => {
    render(
      <VisualWorkspaceBoundary>
        <Example />
      </VisualWorkspaceBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(screen.getByRole("region")).toHaveAttribute("data-visual-workspace", "fullscreen");
    expect(
      within(screen.getByRole("region")).getByRole("tab", { name: "Preview" }),
    ).toBeInTheDocument();
  });

  it("renders no reserved space without a workspace and rejects a missing provider", () => {
    const view = render(<VisualWorkspaceSlot />);
    expect(view.container).toBeEmptyDOMElement();
    expect(() => renderHook(() => useVisualWorkspace("missing"))).toThrow(
      "A visual requires VisualWorkspaceProvider",
    );
  });

  it("releases side space when the selected drawing is removed", () => {
    const view = render(<Harness two />);
    fireEvent.click(screen.getByRole("button", { name: "Open one" }));
    expect(screen.getByRole("region")).toBeInTheDocument();
    view.rerender(<Harness two visible={false} />);
    expect(screen.queryByRole("region")).toBeNull();
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
    await waitFor(() => expect(screen.queryByRole("region")).toBeNull());
    expect(screen.getByTitle("one")).toBe(frame);
    dialog.remove();
  });
});
