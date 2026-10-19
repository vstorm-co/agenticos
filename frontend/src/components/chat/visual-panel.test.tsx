import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VisualFrameProps } from "./visual-frame";
import { ConversationVisualsProvider, TurnVisuals } from "./visual-panel";
import {
  useSavedVisualsStore,
  useVisualImagesStore,
  useVisualStreamStore,
} from "@/stores/visual-stream-store";
import type { ChatMessage, ToolCall } from "@/types";

const frames: VisualFrameProps[] = [];
vi.mock("./visual-frame", () => ({
  VisualFrame: (props: VisualFrameProps) => {
    frames.push(props);
    return (
      <div data-testid={props.fill ? "full-frame" : "frame"} data-done={String(props.done)}>
        {props.content}
      </div>
    );
  },
}));

const { copySvgImage, downloadVisual, svgPng } = vi.hoisted(() => ({
  copySvgImage: vi.fn(),
  downloadVisual: vi.fn(),
  svgPng: vi.fn(),
}));
vi.mock("./visual-actions", () => ({ copySvgImage, downloadVisual, svgPng }));

const { getVisualImage, putVisualThumbnail } = vi.hoisted(() => ({
  getVisualImage: vi.fn(),
  putVisualThumbnail: vi.fn(),
}));
vi.mock("@/lib/visuals-api", () => ({ getVisualImage, putVisualThumbnail }));

const { nested } = vi.hoisted(() => ({ nested: { value: false } }));
vi.mock("@/lib/visuals", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/visuals")>()),
  framedElsewhere: () => nested.value,
}));

vi.mock("./visual-save-dialog", () => ({
  VisualSaveDialog: (props: { visualId: string; updates: string | null }) => (
    <div data-testid="save-dialog">
      {props.visualId}:{props.updates ?? "new"}
    </div>
  ),
}));

const { toast } = vi.hoisted(() => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast }));

// Saving publishes an app, which `artifacts:edit` decides.
const canPublish = vi.fn(() => true);
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => canPublish() }),
}));

const SVG = '<svg viewBox="0 0 10 10"><rect/></svg>';

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "d1",
    name: "draw",
    args: { title: "Flow", kind: "svg", height: 400, content: SVG },
    status: "completed",
    ...overrides,
  };
}

function lastFrame(): VisualFrameProps {
  return frames.at(-1)!;
}

function show(
  calls: ToolCall[],
  options: {
    known?: ToolCall[];
    conversationId?: string | null;
    onReport?: (id: string, errors: string[]) => void;
    onCompose?: (text: string) => void;
  } = {},
) {
  const messages: ChatMessage[] = [
    {
      id: "m",
      role: "assistant",
      content: "",
      timestamp: new Date(),
      toolCalls: options.known ?? calls,
    } as ChatMessage,
  ];
  return render(
    <ConversationVisualsProvider
      messages={messages}
      conversationId={options.conversationId === undefined ? "c1" : options.conversationId}
      onReport={options.onReport}
      onCompose={options.onCompose}
    >
      <TurnVisuals calls={calls} />
    </ConversationVisualsProvider>,
  );
}

describe("TurnVisuals", () => {
  beforeEach(() => {
    frames.length = 0;
    useVisualStreamStore.setState({ args: {} });
    useVisualImagesStore.setState({ images: {} });
    useSavedVisualsStore.setState({ saved: {} });
    vi.clearAllMocks();
  });

  it("forgets the visuals' pictures when another conversation takes the screen", () => {
    useVisualImagesStore.setState({ images: { call_0: { logo: "data:a" } } });
    const { rerender } = show([]);
    const provider = (conversationId: string | null) => (
      <ConversationVisualsProvider messages={[]} conversationId={conversationId}>
        <TurnVisuals calls={[]} />
      </ConversationVisualsProvider>
    );

    // A new thread learning its id mid-turn keeps what the turn is drawing with.
    rerender(provider(null));
    useVisualImagesStore.setState({ images: { call_0: { logo: "data:b" } } });
    rerender(provider("c2"));
    expect(useVisualImagesStore.getState().images).toEqual({ call_0: { logo: "data:b" } });

    rerender(provider("c3"));
    expect(useVisualImagesStore.getState().images).toEqual({});
  });

  it("draws nothing for a turn that drew nothing", () => {
    const { container } = show([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a finished drawing under its title alone", () => {
    show([call()]);
    expect(screen.getByText("Flow")).toBeInTheDocument();
    expect(screen.queryByText("SVG")).toBeNull();
    expect(lastFrame()).toMatchObject({
      done: true,
      aspect: 1,
      content: SVG,
      height: 400,
      zoom: 1,
    });
  });

  it("zooms the preview and full screen each on their own", () => {
    show([call()]);
    const [zoomOut, zoomIn] = [
      screen.getByRole("button", { name: "Zoom out" }),
      screen.getByRole("button", { name: "Zoom in" }),
    ];
    fireEvent.click(zoomIn);
    fireEvent.click(zoomIn);
    expect(lastFrame().zoom).toBe(1.5);
    expect(screen.getByRole("button", { name: "Reset zoom" })).toHaveTextContent("150%");
    fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));
    expect(lastFrame().zoom).toBe(1);
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    expect(lastFrame().zoom).toBe(0.5);
    expect(zoomOut).toBeDisabled();

    fireEvent.click(screen.getAllByRole("button", { name: "Full screen" })[0]!);
    expect(lastFrame()).toMatchObject({ fill: true, zoom: 1 });
    const fullZoomIn = screen.getAllByRole("button", { name: "Zoom in" }).at(-1)!;
    for (let step = 0; step < 6; step += 1) fireEvent.click(fullZoomIn);
    expect(lastFrame()).toMatchObject({ fill: true, zoom: 4 });
    expect(fullZoomIn).toBeDisabled();
  });

  it("offers no zoom over the code", () => {
    show([call()]);
    fireEvent.click(screen.getByRole("button", { name: "Show code" }));
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
  });

  it("shows nothing for a call that failed", () => {
    const { container } = show([call({ status: "error" })]);
    expect(container.querySelector("[data-tour]")).toBeNull();
  });

  it("shows nothing for a call the tool refused, though it finished", () => {
    // A retry prompt or the last attempt's refusal is a finished call that drew nothing.
    const { container } = show([
      call({ result: "The visual pulls a script from the web; draw it inline." }),
    ]);
    expect(container.querySelector("[data-tour]")).toBeNull();
  });

  it("offers saving as an app only to whoever may publish one", () => {
    const { unmount } = show([call({ result: "Drew 'Flow' as visual `d1`." })]);
    expect(screen.getByRole("button", { name: "Save to Apps" })).toBeInTheDocument();
    unmount();

    canPublish.mockReturnValue(false);
    show([call({ result: "Drew 'Flow' as visual `d1`." })]);
    expect(screen.queryByRole("button", { name: "Save to Apps" })).toBeNull();
    canPublish.mockReturnValue(true);
  });

  it("holds a place while nothing has streamed yet", () => {
    show([call({ args: {}, status: "pending" })]);
    expect(screen.getByText("Drawing…")).toBeInTheDocument();
  });

  it("draws what has streamed, inert, while the call is written", () => {
    useVisualStreamStore.setState({
      args: { d1: '{"title": "Flow", "kind": "html", "height": 300, "content": "<p>par' },
    });
    show([call({ args: {}, status: "pending" })]);
    expect(lastFrame()).toMatchObject({
      done: false,
      content: "<p>par",
      kind: "html",
      height: 300,
    });
    expect(screen.getByText("Drawing…")).toBeInTheDocument();
  });

  it("reads a provider that streams objects instead of text", () => {
    useVisualStreamStore.setState({
      args: { d1: { title: "Flow", kind: "mermaid", content: "graph TD" } },
    });
    show([call({ args: {}, status: "pending" })]);
    expect(lastFrame()).toMatchObject({ kind: "mermaid", content: "graph TD", height: 480 });
  });

  it("shows nothing for a finished call that is not a drawing it can rebuild", () => {
    const { container } = show([call({ args: { kind: "pdf", content: "x" } })]);
    expect(container.querySelector("[data-tour]")).toBeNull();
  });

  it("shows the visual being revised until the revision is whole", () => {
    useVisualStreamStore.setState({ args: { r1: '{"visual_id": "d1", "edits": [' } });
    const revision = call({ id: "r1", name: "revise_visual", args: {}, status: "pending" });
    show([revision], { known: [call(), revision] });
    expect(screen.getByText("Revising…")).toBeInTheDocument();
    expect(lastFrame()).toMatchObject({ done: false, content: SVG });
  });

  it("holds a place for a revision of something not loaded", () => {
    useVisualStreamStore.setState({ args: { r1: '{"visual_id": "gone"' } });
    show([call({ id: "r1", name: "revise_visual", args: {}, status: "pending" })]);
    expect(screen.getByText("Drawing…")).toBeInTheDocument();
  });

  it("names the visual a finished revision changed", () => {
    const revision = call({
      id: "r1",
      name: "revise_visual",
      args: { visual_id: "d1", edits: [{ old: "<rect/>", new: "<circle/>" }] },
    });
    show([revision], { known: [call(), revision] });
    expect(screen.getByText("Revision of Flow")).toBeInTheDocument();
    expect(lastFrame().content).toContain("<circle/>");
  });

  it("says when a revision's visual is not in the loaded conversation", () => {
    show([call({ id: "r1", name: "revise_visual", args: { visual_id: "gone", edits: [] } })]);
    expect(
      screen.getByText("The visual this revises is not in the loaded conversation."),
    ).toBeInTheDocument();
  });

  it("shows a drawing a stopped turn left unfinished, without running it", () => {
    show([call({ status: "unfinished" })]);
    expect(screen.getByText("Unfinished")).toBeInTheDocument();
    expect(lastFrame().done).toBe(false);
  });

  it("toggles to the code and back", () => {
    show([call()]);
    fireEvent.click(screen.getByRole("button", { name: "Show code" }));
    expect(screen.getByText(SVG)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show visual" }));
    expect(screen.getByTestId("frame")).toBeInTheDocument();
  });

  it("downloads and copies an SVG", async () => {
    copySvgImage.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("no"));
    show([call()]);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(downloadVisual).toHaveBeenCalledWith(
      "Flow",
      "svg",
      SVG,
      // Where the frame is served, so a downloaded page finds its libraries.
      "http://localhost:8000/api/v1/artifact-content/",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy as image" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Image copied"));
    fireEvent.click(screen.getByRole("button", { name: "Copy as image" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("opens full screen from the button, and closes it", () => {
    show([call()]);
    fireEvent.click(screen.getAllByRole("button", { name: "Full screen" })[0]!);
    expect(screen.getByTestId("full-frame")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByTestId("full-frame")).toBeNull();
  });

  it("opens full screen from a tap on the preview, as a phone does", () => {
    show([call()]);
    fireEvent.click(screen.getAllByRole("button", { name: "Full screen" })[1]!);
    expect(screen.getByTestId("full-frame")).toBeInTheDocument();
  });

  it("asks the agent to fix what the drawing reported", () => {
    const onCompose = vi.fn();
    show([call()], { onCompose });

    act(() => lastFrame().onError?.("boom"));
    act(() => lastFrame().onError?.("boom"));
    expect(screen.getByText("The drawing reported an error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fix it" }));
    expect(onCompose).toHaveBeenLastCalledWith(
      "The visual “Flow” (d1) reported these errors:\nboom\nPlease fix it.",
    );
  });

  it("tells a running turn how the drawing rendered, once", () => {
    const onReport = vi.fn();
    show([call({ status: "running" })], { onReport });
    act(() => lastFrame().onError?.("Blocked: x"));
    act(() => lastFrame().onRendered?.());
    act(() => lastFrame().onRendered?.());
    expect(onReport).toHaveBeenCalledTimes(1);
    expect(onReport).toHaveBeenCalledWith("d1", ["Blocked: x"]);
  });

  it("tells nobody about a drawing read back from the transcript", () => {
    const onReport = vi.fn();
    show([call()], { onReport });
    act(() => lastFrame().onRendered?.());
    expect(onReport).not.toHaveBeenCalled();
  });

  it("offers a reload when the drawing stops responding", () => {
    show([call()]);
    act(() => lastFrame().onError?.("x"));
    act(() => lastFrame().onStall?.());
    expect(
      screen.getByText("The drawing stopped responding, so it was closed."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(screen.getByTestId("frame")).toBeInTheDocument();
    expect(screen.queryByText("The drawing reported an error")).toBeNull();
  });

  it("saves to Apps, and offers to update the app a base was saved as", () => {
    useSavedVisualsStore.setState({
      saved: { d1: { artifactId: "a", name: "flow", version: 1, url: "/apps/a" } },
    });
    const revision = call({
      id: "r1",
      name: "revise_visual",
      args: { visual_id: "d1", edits: [{ old: "<rect/>", new: "<g/>" }] },
    });
    show([call(), revision], { known: [call(), revision] });

    expect(screen.getByRole("link", { name: "Saved · v1" })).toHaveAttribute("href", "/apps/a");
    const buttons = screen.getAllByRole("button", { name: "Update the app" });
    fireEvent.click(buttons[1]!);
    expect(screen.getByTestId("save-dialog")).toHaveTextContent("r1:flow");
  });

  it("does not offer to save where there is no conversation", () => {
    show([call()], { conversationId: null });
    expect(screen.queryByRole("button", { name: "Save to Apps" })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Full screen" })[0]!);
  });

  it("opens the save dialog for a new app", () => {
    show([call()]);
    fireEvent.click(screen.getByRole("button", { name: "Save to Apps" }));
    expect(screen.getByTestId("save-dialog")).toHaveTextContent("d1:new");
  });
});

describe("pictures", () => {
  const withPicture = call({
    args: {
      title: "Poster",
      kind: "html",
      height: 400,
      content: '<img src="{{image:logo}}">',
      images: [{ name: "logo", source: "logo.png" }],
    },
  });

  beforeEach(() => {
    frames.length = 0;
    useVisualImagesStore.setState({ images: {} });
    vi.clearAllMocks();
  });

  it("draws with the pictures the socket already sent", () => {
    useVisualImagesStore.setState({ images: { d1: { logo: "data:image/png;base64,AA" } } });
    show([withPicture]);
    expect(lastFrame()).toMatchObject({
      done: true,
      content: '<img src="data:image/png;base64,AA">',
    });
    expect(getVisualImage).not.toHaveBeenCalled();
  });

  it("asks for a picture of a drawing read back, and draws once it has it", async () => {
    getVisualImage.mockResolvedValue("data:image/png;base64,BB");
    show([withPicture]);
    expect(lastFrame().done).toBe(false);
    await waitFor(() => expect(lastFrame().done).toBe(true));
    expect(getVisualImage).toHaveBeenCalledWith("c1", "d1", "logo");
    expect(lastFrame().content).toBe('<img src="data:image/png;base64,BB">');
  });

  it("draws without a picture it cannot have", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    getVisualImage.mockRejectedValue(new Error("404"));
    show([withPicture]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(getVisualImage).toHaveBeenCalledTimes(3);
    expect(lastFrame().done).toBe(true);
    expect(lastFrame().content).toBe('<img src="{{image:logo}}">');
    vi.useRealTimers();
  });

  it("asks nobody for pictures where there is no conversation", () => {
    show([withPicture], { conversationId: null });
    expect(getVisualImage).not.toHaveBeenCalled();
    expect(lastFrame().done).toBe(false);
  });

  it("stops asking once the panel is gone", async () => {
    getVisualImage.mockImplementation(
      () => new Promise((_resolve, reject) => setTimeout(() => reject(new Error("x")), 10)),
    );
    const { unmount } = show([withPicture]);
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getVisualImage).toHaveBeenCalledTimes(1);
  });
});

describe("inside another site's frame", () => {
  beforeEach(() => {
    frames.length = 0;
    nested.value = true;
  });

  it("shows an SVG as a picture, with no frame", () => {
    show([call()]);
    expect(screen.queryByTestId("frame")).toBeNull();
    const picture = screen.getByRole("img", { name: "Flow" });
    expect(picture.getAttribute("src")).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
    nested.value = false;
  });

  it("names a page it cannot draw here", () => {
    show([call({ args: { title: "Explainer", kind: "html", content: "<p/>" } })]);
    expect(screen.getByText("Explainer")).toBeInTheDocument();
    expect(screen.getByText("Shown in AgenticOS")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
    nested.value = false;
  });
});

describe("on the server", () => {
  it("renders the framed panel, since no server page is inside another site", () => {
    const html = renderToString(<TurnVisuals calls={[call()]} />);
    expect(html).toContain("Flow");
    expect(html).toContain('data-testid="frame"');
  });

  it("lets go of the page when the panel goes", () => {
    const { unmount } = show([call()]);
    unmount();
    expect(screen.queryByText("Flow")).toBeNull();
  });
});

describe("thumbnails", () => {
  beforeEach(() => {
    frames.length = 0;
    nested.value = false;
    vi.clearAllMocks();
    svgPng.mockResolvedValue(new Blob(["png"]));
    putVisualThumbnail.mockResolvedValue(undefined);
  });

  it("keeps one thumbnail of a drawing rendered live, from its own source", async () => {
    show([call({ status: "running" })]);
    act(() => lastFrame().onSvg?.("<svg>rendered</svg>"));
    act(() => lastFrame().onSvg?.("<svg>again</svg>"));
    await waitFor(() => expect(putVisualThumbnail).toHaveBeenCalledTimes(1));
    expect(svgPng).toHaveBeenCalledWith(SVG, 640);
    expect(putVisualThumbnail.mock.calls[0]!.slice(0, 2)).toEqual(["c1", "d1"]);
  });

  it("thumbnails a Mermaid diagram from what the frame rendered", async () => {
    show([call({ status: "running", args: { title: "F", kind: "mermaid", content: "graph TD" } })]);
    act(() => lastFrame().onSvg?.("<svg>diagram</svg>"));
    await waitFor(() => expect(svgPng).toHaveBeenCalledWith("<svg>diagram</svg>", 640));
  });

  it("leaves a page, a reloaded drawing and a thread with no conversation alone", () => {
    show([call({ status: "running", args: { title: "P", kind: "html", content: "<p/>" } })]);
    act(() => lastFrame().onSvg?.("<svg/>"));
    show([call()]);
    act(() => lastFrame().onSvg?.("<svg/>"));
    show([call({ status: "running" })], { conversationId: null });
    act(() => lastFrame().onSvg?.("<svg/>"));
    expect(svgPng).not.toHaveBeenCalled();
  });

  it("shrugs off a thumbnail that could not be made", async () => {
    svgPng.mockRejectedValue(new Error("no canvas"));
    show([call({ status: "running" })]);
    act(() => lastFrame().onSvg?.("<svg/>"));
    await waitFor(() => expect(svgPng).toHaveBeenCalled());
    expect(putVisualThumbnail).not.toHaveBeenCalled();
  });
});
