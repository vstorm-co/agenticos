import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { BrowserCommentLayer, ringedPicture } from "./browser-comment";

const IMAGE = "data:image/png;base64,AAA";

/** jsdom draws nothing: a picture that decodes, and a canvas that records its strokes. */
function fakeCanvas(blob: Blob | null = new Blob(["png"], { type: "image/png" })) {
  // jsdom has no image decoder at all.
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    value: () => Promise.resolve(),
  });
  vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(1000);
  vi.spyOn(HTMLImageElement.prototype, "naturalHeight", "get").mockReturnValue(800);
  const context = {
    drawImage: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    stroke: vi.fn(),
    lineWidth: 0,
    strokeStyle: "",
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((done) => done(blob));
  return context;
}

afterEach(() => vi.restoreAllMocks());

function renderLayer(url: string | null = "https://example.test/pricing") {
  const onComment = vi.fn();
  const onDone = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <div style={{ position: "relative", width: 400, height: 300 }}>
        <BrowserCommentLayer image={IMAGE} url={url} onComment={onComment} onDone={onDone} />
      </div>
    </NextIntlClientProvider>,
  );
  const layer = screen.getByTestId("browser-comment-layer");
  vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 400,
    height: 300,
  } as DOMRect);
  return { onComment, onDone, layer };
}

describe("a comment pointed at the browser's page", () => {
  it("asks for a spot, then a note, and hands both to the composer", async () => {
    const context = fakeCanvas();
    const { onComment, onDone, layer } = renderLayer();
    expect(screen.getByText("Click the spot you mean")).toBeInTheDocument();

    fireEvent.click(layer, { clientX: 100, clientY: 150 });
    await userEvent.type(screen.getByLabelText("What about it?"), "Why is this greyed out?{Enter}");

    await vi.waitFor(() => expect(onComment).toHaveBeenCalledTimes(1));
    const [{ file, text }] = onComment.mock.calls[0]!;
    expect(file.name).toBe("browser-comment.jpg");
    expect(text).toBe(
      "On https://example.test/pricing - the spot ringed in the picture: Why is this greyed out?",
    );
    // Ringed where it was clicked: a quarter across, half down.
    expect(context.arc.mock.calls[0]!.slice(0, 2)).toEqual([250, 400]);
    expect(onDone).toHaveBeenCalled();
  });

  it("keeps the first spot, and sends the note alone where the page has no address", async () => {
    fakeCanvas();
    const { onComment, layer } = renderLayer(null);

    fireEvent.click(layer, { clientX: 10, clientY: 280 });
    fireEvent.click(layer, { clientX: 300, clientY: 20 });
    await userEvent.type(screen.getByLabelText("What about it?"), "this");
    await userEvent.click(screen.getByRole("button", { name: "Add to message" }));

    await vi.waitFor(() =>
      expect(onComment).toHaveBeenCalledWith(expect.objectContaining({ text: "this" })),
    );
  });

  it("sends nothing without a note, and stops on Cancel or Escape", async () => {
    const { onComment, onDone, layer } = renderLayer();
    fireEvent.click(layer, { clientX: 100, clientY: 100 });

    expect(screen.getByRole("button", { name: "Add to message" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("What about it?"), "{Enter}");
    expect(onComment).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.type(screen.getByLabelText("What about it?"), "{Escape}");
    expect(onDone).toHaveBeenCalledTimes(2);
  });
});

describe("ringedPicture", () => {
  it("refuses where the browser has no canvas to draw on", async () => {
    fakeCanvas();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    await expect(ringedPicture(IMAGE, { x: 0.5, y: 0.5 })).rejects.toThrow("no 2d canvas");
  });

  it("refuses where the canvas gives no picture back", async () => {
    fakeCanvas(null);
    await expect(ringedPicture(IMAGE, { x: 0.5, y: 0.5 })).rejects.toThrow("no picture");
  });
});
