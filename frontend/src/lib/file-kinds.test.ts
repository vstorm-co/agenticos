import { describe, expect, it } from "vitest";

import {
  codeLanguage,
  hasSourceView,
  readsAsText,
  resolveFileKind,
  suffixOf,
  type FileKind,
} from "./file-kinds";

/** What a path says about the file at the end of it. */
describe("reading a path", () => {
  it("takes the suffix off the name, not off the folders", () => {
    expect(suffixOf("/skills/code-review/SKILL.md")).toBe("md");
  });

  it("has no suffix for a file with none", () => {
    expect(suffixOf("/Makefile")).toBe("");
    expect(suffixOf("/.env")).toBe("");
  });

  it("lowercases it, because a listing does not", () => {
    expect(suffixOf("/CHART.PNG")).toBe("png");
  });

  it("reads the last of several", () => {
    expect(suffixOf("archive.tar.gz")).toBe("gz");
  });
});

/**
 * One answer to "what kind of file is this".
 *
 * There were three - `resolveViewerKind` for a knowledge base document, `previewKind`
 * for a composer attachment, and `isTextual`/`isMarkdown` for a workspace file - and a
 * `.csv` an agent wrote was a spreadsheet to the icon, plain text to the viewer and a
 * table to the composer's card, on the same screen.
 */
describe("deciding what a file is", () => {
  it("trusts a media type that says something specific", () => {
    expect(resolveFileKind("x", "application/pdf")).toBe("pdf");
    expect(resolveFileKind("x", "image/png")).toBe("image");
    expect(resolveFileKind("x", "video/mp4")).toBe("video");
    expect(resolveFileKind("x", "audio/mpeg")).toBe("audio");
    expect(resolveFileKind("x", "text/html")).toBe("html");
    expect(resolveFileKind("x", "text/markdown")).toBe("markdown");
    expect(resolveFileKind("x", "text/csv")).toBe("csv");
    expect(resolveFileKind("x", "text/tab-separated-values")).toBe("csv");
    expect(resolveFileKind("x", "application/json")).toBe("json");
    expect(resolveFileKind("x", "application/javascript")).toBe("code");
    expect(resolveFileKind("x", "application/xml")).toBe("code");
    expect(resolveFileKind("x", "application/x-yaml")).toBe("code");
    expect(resolveFileKind("x", "application/yaml")).toBe("code");
    expect(resolveFileKind("x", "application/zip")).toBe("archive");
    expect(resolveFileKind("x", "application/gzip")).toBe("archive");
  });

  it("ignores the parameters a media type carries, and its case", () => {
    expect(resolveFileKind("x", "text/csv; charset=utf-8")).toBe("csv");
    expect(resolveFileKind("x", "IMAGE/PNG")).toBe("image");
  });

  it("falls back to the name when the type says nothing useful", () => {
    // Which is every drag-and-drop of a type the browser does not recognise.
    const octet = "application/octet-stream";
    expect(resolveFileKind("chart.png", octet)).toBe("image");
    expect(resolveFileKind("report.pdf", octet)).toBe("pdf");
    expect(resolveFileKind("call.mp3", octet)).toBe("audio");
    expect(resolveFileKind("demo.webm", octet)).toBe("video");
    expect(resolveFileKind("rows.tsv", octet)).toBe("csv");
    expect(resolveFileKind("page.htm", octet)).toBe("html");
    expect(resolveFileKind("conf.jsonc", octet)).toBe("json");
    expect(resolveFileKind("notes.mdx", octet)).toBe("markdown");
    expect(resolveFileKind("run.py", octet)).toBe("code");
    expect(resolveFileKind("out.log", octet)).toBe("text");
    expect(resolveFileKind("books.xlsx", octet)).toBe("spreadsheet");
    expect(resolveFileKind("brief.docx", octet)).toBe("document");
    expect(resolveFileKind("bundle.zip", octet)).toBe("archive");
  });

  it("prefers a specific name over a type as broad as text/plain", () => {
    // A knowledge base stores `text/plain` for a Markdown upload often enough that
    // trusting it would render every report as raw asterisks.
    expect(resolveFileKind("notes.md", "text/plain")).toBe("markdown");
    expect(resolveFileKind("run.py", "text/plain")).toBe("code");
  });

  it("reads a text/* it knows nothing more about as text", () => {
    expect(resolveFileKind("Makefile", "text/x-makefile")).toBe("text");
  });

  it("calls an SVG markup, whichever half says so", () => {
    // The one image whose bytes are a document with script in it, which is why the
    // API refuses to serve one inline. Its source is showable and safe; a rendered
    // SVG from this origin is stored XSS with the agent as its author.
    expect(resolveFileKind("logo.svg")).toBe("code");
    expect(resolveFileKind("logo", "image/svg+xml")).toBe("code");
  });

  it("is `unknown` for a file it can say nothing about", () => {
    expect(resolveFileKind("blob.bin")).toBe("unknown");
    expect(resolveFileKind("Makefile")).toBe("unknown");
    expect(resolveFileKind("x", "application/octet-stream")).toBe("unknown");
  });
});

/**
 * Which request a file gets, which is the only thing the kind decides here.
 *
 * Whether the answer can be *shown* is the server's call, read off the response type -
 * so `.svg` asks for its characters like any other markup, and it is the API refusing
 * to serve one inline that keeps a rendered one off the screen.
 */
describe("choosing text or bytes", () => {
  it("asks for characters for what is made of them", () => {
    for (const name of ["/report.csv", "/notes.md", "/logo.svg", "/page.html", "/a.json", "/x.py"])
      expect(readsAsText(resolveFileKind(name))).toBe(true);
  });

  it("asks for bytes for a picture, a PDF and anything it does not know", () => {
    for (const name of ["/chart.png", "/report.pdf", "/Makefile", "/books.xlsx", "/b.zip"])
      expect(readsAsText(resolveFileKind(name))).toBe(false);
  });
});

/**
 * Where a rendered view and the characters are two different things.
 *
 * Markdown *and* HTML, where it used to be Markdown alone - and a table hides which
 * delimiter a CSV used, so that counts too.
 */
describe("offering the source as well", () => {
  it("offers both wherever the preview transforms the file", () => {
    for (const kind of ["markdown", "html", "csv", "json"] as FileKind[])
      expect(hasSourceView(kind)).toBe(true);
  });

  it("does not offer the same characters twice", () => {
    // Fencing code adds colour and takes nothing away; the other kinds have no
    // rendered form for a toggle to switch away from.
    for (const kind of ["code", "text", "pdf", "image", "unknown"] as FileKind[])
      expect(hasSourceView(kind)).toBe(false);
  });
});

describe("fencing a code file", () => {
  it("names the language highlight.js knows it by, not the extension", () => {
    expect(codeLanguage("run.py")).toBe("python");
    expect(codeLanguage("main.rs")).toBe("rust");
    expect(codeLanguage("app.tsx")).toBe("tsx");
    expect(codeLanguage("deploy.sh")).toBe("bash");
    expect(codeLanguage("logo.svg")).toBe("xml");
  });

  it("falls back to plain text for a language nobody mapped", () => {
    expect(codeLanguage("thing.unknownlang")).toBe("text");
    expect(codeLanguage("Makefile")).toBe("text");
  });
});
