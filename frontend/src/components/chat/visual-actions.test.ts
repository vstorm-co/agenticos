import { afterEach, describe, expect, it, vi } from "vitest";

import { copySvgImage, downloadVisual } from "./visual-actions";

describe("downloadVisual", () => {
  it("saves the drawing under a name made from its title", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    downloadVisual("Order flow", "mermaid", "graph TD");

    const blob = created.mock.calls[0]![0] as Blob;
    expect(blob.type).toBe("text/plain;charset=utf-8");
    const link = click.mock.contexts[0] as HTMLAnchorElement;
    expect(link.download).toBe("order-flow.mmd");
    expect(revoked).toHaveBeenCalledWith("blob:x");
    click.mockRestore();
    created.mockRestore();
    revoked.mockRestore();
  });
});

describe("copySvgImage", () => {
  // jsdom has no `decode`; the browser does, and it is what waits for the image.
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    value: () => Promise.resolve(),
  });
  afterEach(() => vi.restoreAllMocks());

  function canvasGives(context: unknown, png: Blob | null) {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      context as CanvasRenderingContext2D,
    );
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((done) => done(png));
  }

  it("draws the SVG through an image, sized by its viewBox, onto the clipboard", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:svg");
    const revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const drawImage = vi.fn();
    canvasGives({ drawImage }, new Blob(["png"], { type: "image/png" }));
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { write } });
    vi.stubGlobal(
      "ClipboardItem",
      class {
        constructor(readonly items: Record<string, Blob>) {}
      },
    );

    await copySvgImage('<svg viewBox="0 0 100 50"></svg>');

    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 2000, 1000);
    expect(write).toHaveBeenCalledTimes(1);
    expect(revoked).toHaveBeenCalledWith("blob:svg");
    vi.unstubAllGlobals();
  });

  it("fails when the browser gives no canvas, or no image", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:svg");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    canvasGives(null, null);
    await expect(copySvgImage("<svg/>")).rejects.toThrow();
    vi.restoreAllMocks();

    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:svg");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    canvasGives({ drawImage: vi.fn() }, null);
    await expect(copySvgImage("<svg/>")).rejects.toThrow();
  });
});
