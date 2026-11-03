import { describe, expect, it, vi } from "vitest";
import {
  HtmlPreviewAssetError,
  prepareHtmlFilePreview,
  relativeAssetPath,
} from "./html-file-preview";

describe("HTML file preview", () => {
  it("reads a sibling stylesheet relative to a nested page and preserves media", async () => {
    const read = vi.fn().mockResolvedValue({ content: "h1 { color: green; }", truncated: false });
    const preview = await prepareHtmlFilePreview(
      "site/index.html",
      {
        content: '<link rel="stylesheet" media="screen" href="style.css?v=1"><h1>Hello</h1>',
        truncated: false,
      },
      read,
    );
    expect(read).toHaveBeenCalledWith("site/style.css");
    expect(preview.content).toContain('<style media="screen">h1{color:green}</style>');
    expect(preview.content).toContain("<h1>Hello</h1>");
  });
  it("leaves remote, inline and empty references alone", async () => {
    const read = vi.fn();
    await prepareHtmlFilePreview(
      "index.html",
      {
        content:
          '<link rel="stylesheet" href="https://example.test/style.css"><link rel="stylesheet" href=""><link rel="stylesheet"><style>p{color:red}</style>',
        truncated: false,
      },
      read,
    );
    expect(read).not.toHaveBeenCalled();
  });
  it("fails visibly when a linked file is missing or shortened", async () => {
    const html = { content: '<link rel="stylesheet" href="style.css">', truncated: false };
    await expect(
      prepareHtmlFilePreview("index.html", html, async () => {
        throw new Error("missing");
      }),
    ).rejects.toMatchObject({ path: "style.css" });
    await expect(
      prepareHtmlFilePreview("index.html", html, async () => ({
        content: "partial",
        truncated: true,
      })),
    ).rejects.toBeInstanceOf(HtmlPreviewAssetError);
  });
  it("bounds linked reads and prevents stylesheet text from closing its element", async () => {
    const html = { content: '<link rel="stylesheet" href="a.css">'.repeat(17), truncated: false };
    const read = vi
      .fn()
      .mockResolvedValue({ content: "/* </style><p>injected</p> */", truncated: false });
    await expect(prepareHtmlFilePreview("index.html", html, read)).rejects.toBeInstanceOf(
      HtmlPreviewAssetError,
    );
    expect(read).not.toHaveBeenCalled();
    const result = await prepareHtmlFilePreview(
      "index.html",
      { ...html, content: '<link rel="stylesheet" href="a.css">' },
      read,
    );
    expect(
      new DOMParser().parseFromString(result.content, "text/html").querySelector("p"),
    ).toBeNull();
  });
});

describe("workspace asset paths", () => {
  it("resolves parent paths inside the root, root paths, spaces and fragments", () => {
    expect(relativeAssetPath("a/b/index.html", "../style.css")).toBe("a/style.css");
    expect(relativeAssetPath("a/index.html", "/style.css")).toBe("style.css");
    expect(relativeAssetPath("index.html", "./my%20style.css#x")).toBe("my style.css");
    expect(relativeAssetPath("index.html", "#x")).toBeNull();
    expect(relativeAssetPath("index.html", "//example.test/a")).toBeNull();
  });
  it("refuses traversal, escaped separators, null bytes and malformed encoding", async () => {
    for (const reference of ["../a.css", "%2e%2e/a.css", "a%5cb.css", "a%00b.css"])
      expect(() => relativeAssetPath("index.html", reference)).toThrow(HtmlPreviewAssetError);
    await expect(
      prepareHtmlFilePreview(
        "index.html",
        { content: '<link rel="stylesheet" href="%zz.css">', truncated: false },
        vi.fn(),
      ),
    ).rejects.toBeInstanceOf(HtmlPreviewAssetError);
  });
});

it("resolves nested stylesheet imports, images and fonts from the stylesheet directory", async () => {
  const read = vi.fn(async (path: string) => ({
    content:
      path === "site/css/main.css"
        ? '@import "theme.css" screen; .hero{background:url(../images/logo.png)}'
        : "@font-face{font-family:local;src:url(../fonts/a.woff2)}",
    truncated: false,
  }));
  const bytes = vi.fn(async () => new Blob(["asset"]));
  const preview = await prepareHtmlFilePreview(
    "site/index.html",
    { content: '<link rel="stylesheet" href="css/main.css">', truncated: false },
    read,
    bytes,
  );
  expect(read.mock.calls.map((call) => call[0])).toEqual([
    "site/css/main.css",
    "site/css/theme.css",
  ]);
  expect(bytes.mock.calls).toHaveLength(2);
  expect(bytes).toHaveBeenCalledWith("site/fonts/a.woff2");
  expect(bytes).toHaveBeenCalledWith("site/images/logo.png");
  expect(preview.content).toContain("data:image/png;base64,");
  const css = /data:text\/css;base64,([A-Za-z0-9+/=]+)/.exec(preview.content)?.[1];
  expect(css).toBeDefined();
  expect(atob(css ?? "")).toContain("data:font/woff2;base64,");
});

it("rejects cyclic imports and missing asset readers rather than showing broken styles", async () => {
  const file = { content: '<link rel="stylesheet" href="a.css">', truncated: false };
  await expect(
    prepareHtmlFilePreview("index.html", file, async () => ({
      content: '@import "a.css";',
      truncated: false,
    })),
  ).rejects.toBeInstanceOf(HtmlPreviewAssetError);
  await expect(
    prepareHtmlFilePreview("index.html", file, async () => ({
      content: "a{background:url(image.png)}",
      truncated: false,
    })),
  ).rejects.toBeInstanceOf(HtmlPreviewAssetError);
});

it("caches repeated styles and binary assets, preserves fragments and leaves absolute URLs", async () => {
  const read = vi.fn(async () => ({
    content:
      "@import url(https://example.test/remote.css);a{background:url(icons.svg#mark)}b{background:url(icons.svg)}c{background:url(data:image/png;base64,eA==)}",
    truncated: false,
  }));
  const bytes = vi.fn(async () => new Blob(["svg"]));
  const preview = await prepareHtmlFilePreview(
    "index.html",
    {
      content: '<link rel="stylesheet" href="a.css"><link rel="stylesheet" href="a.css">',
      truncated: false,
    },
    read,
    bytes,
  );
  expect(read).toHaveBeenCalledOnce();
  expect(bytes).toHaveBeenCalledOnce();
  expect(preview.content).toContain("#mark");
  expect(preview.content).toContain("https://example.test/remote.css");
});

it("processes URL imports and custom-property assets using their own directory", async () => {
  const read = vi.fn(async (path: string) => ({
    content:
      path === "css/a.css" ? '@import url("nested.css");' : ":root{--image:url(asset.unknown)}",
    truncated: false,
  }));
  const bytes = vi.fn(async () => new Blob(["x"], { type: "image/custom" }));
  await prepareHtmlFilePreview(
    "index.html",
    { content: '<link rel="stylesheet" href="css/a.css">', truncated: false },
    read,
    bytes,
  );
  expect(bytes).toHaveBeenCalledWith("css/asset.unknown");
});

it.each(["depth", "count", "bytes", "output", "text", "read"])(
  "bounds stylesheet %s failures",
  async (mode) => {
    const html = { content: '<link rel="stylesheet" href="0.css">', truncated: false };
    const read = async (path: string) => ({
      truncated: false,
      content:
        mode === "depth"
          ? `@import "${Number(path.split(".")[0]) + 1}.css";`
          : mode === "count"
            ? Array.from({ length: 64 }, (_, i) => `.a${i}{background:url(a${i}.png)}`).join("")
            : mode === "text"
              ? "x".repeat(8 * 1024 * 1024 + 1)
              : mode === "output"
                ? Array.from({ length: 16 }, (_, i) => `.a${i}{background:url(a.png)}`).join("")
                : "a{background:url(a.unknown)}",
    });
    const bytes = async () => {
      if (mode === "read") throw new Error("Unavailable");
      return new Blob([
        new Uint8Array(
          mode === "bytes" ? 8 * 1024 * 1024 + 1 : mode === "output" ? 1024 * 1024 : 0,
        ),
      ]);
    };
    await expect(prepareHtmlFilePreview("index.html", html, read, bytes)).rejects.toBeInstanceOf(
      HtmlPreviewAssetError,
    );
  },
);

it.each(["load", "error"])("surfaces an asset reader %s failure", async (event) => {
  const OriginalReader = FileReader;
  vi.stubGlobal(
    "FileReader",
    class extends OriginalReader {
      override readAsDataURL(): void {
        this.dispatchEvent(new ProgressEvent(event));
      }
    },
  );
  try {
    await expect(
      prepareHtmlFilePreview(
        "index.html",
        { content: '<link rel="stylesheet" href="a.css">', truncated: false },
        async () => ({ content: "a{background:url(a.png)}", truncated: false }),
        async () => new Blob(["x"]),
      ),
    ).rejects.toBeInstanceOf(HtmlPreviewAssetError);
  } finally {
    vi.unstubAllGlobals();
  }
});
