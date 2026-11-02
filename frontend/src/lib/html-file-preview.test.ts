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
    expect(preview.content).toContain('<style media="screen">h1 { color: green; }</style>');
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
