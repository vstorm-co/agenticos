import { generate, parse, walk, type StringNode, type Url } from "css-tree";
import type { FileText } from "./file-access";
import { HtmlPreviewAssetError, relativeAssetPath } from "./preview-asset-path";

const MAX_ASSETS = 64;
const MAX_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT = 16 * 1024 * 1024;
const MAX_DEPTH = 4;
const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  svg: "image/svg+xml",
  webp: "image/webp",
  avif: "image/avif",
  woff: "font/woff",
  woff2: "font/woff2",
  ttf: "font/ttf",
  otf: "font/otf",
};

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      typeof reader.result === "string"
        ? resolve(reader.result)
        : reject(new Error("HTML_PREVIEW_ASSET"));
    reader.onerror = () => reject(reader.error ?? new Error("HTML_PREVIEW_ASSET"));
    reader.readAsDataURL(blob);
  });
}

/** One preview owns its authorized reads, recursion, cache and expansion budgets. */
export class WorkspacePreviewAssets {
  private files = 0;
  private bytes = 0;
  private output = 0;
  private readonly styles = new Map<string, string>();
  private readonly urls = new Map<string, string>();

  constructor(
    private readonly readText: (path: string) => Promise<FileText>,
    private readonly readBytes: ((path: string) => Promise<Blob>) | undefined,
  ) {}

  resolve(path: string, reference: string): string | null {
    return relativeAssetPath(path, reference);
  }

  include(content: string): void {
    this.output += new TextEncoder().encode(content).length;
    if (this.output > MAX_OUTPUT) throw new HtmlPreviewAssetError("preview");
  }

  private reserve(path: string): void {
    if (++this.files > MAX_ASSETS) throw new HtmlPreviewAssetError(path);
  }

  private account(path: string, bytes: number): void {
    this.bytes += bytes;
    if (this.bytes > MAX_BYTES) throw new HtmlPreviewAssetError(path);
  }

  async stylesheet(path: string, parents: string[] = []): Promise<string> {
    if (parents.includes(path) || parents.length > MAX_DEPTH) throw new HtmlPreviewAssetError(path);
    const cached = this.styles.get(path);
    if (cached !== undefined) return cached;
    this.reserve(path);
    const file = await this.readText(path);
    if (file.truncated || file.content.length > MAX_BYTES) throw new HtmlPreviewAssetError(path);
    this.account(path, new TextEncoder().encode(file.content).length);
    const ast = parse(file.content, { parseCustomProperty: true });
    const imports: (Url | StringNode)[] = [];
    const urls: Url[] = [];
    walk(ast, (node) => {
      if (
        node.type === "Atrule" &&
        node.name.toLowerCase() === "import" &&
        node.prelude?.type === "AtrulePrelude"
      ) {
        const first = node.prelude.children.first;
        if (first?.type === "Url" || first?.type === "String") imports.push(first);
      }
      if (node.type === "Url") urls.push(node);
    });
    for (const node of imports) {
      const asset = this.resolve(path, node.value);
      if (asset === null) continue;
      const nested = await this.stylesheet(asset, [...parents, path]);
      const value = await dataUrl(new Blob([nested], { type: "text/css" }));
      this.include(value);
      node.value = value;
    }
    for (const node of urls) {
      if (imports.includes(node)) continue;
      const asset = this.resolve(path, node.value);
      if (asset === null) continue;
      const fragment = node.value.includes("#") ? node.value.slice(node.value.indexOf("#")) : "";
      const value = (await this.assetUrl(asset)) + fragment;
      this.include(value);
      node.value = value;
    }
    const result = generate(ast);
    this.styles.set(path, result);
    return result;
  }

  private async assetUrl(path: string): Promise<string> {
    const cached = this.urls.get(path);
    if (cached !== undefined) return cached;
    if (!this.readBytes) throw new HtmlPreviewAssetError(path);
    this.reserve(path);
    const file = await this.readBytes(path);
    this.account(path, file.size);
    const extension = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
    const type = MIME[extension] ?? (file.type || "application/octet-stream");
    const result = await dataUrl(new Blob([file], { type }));
    this.urls.set(path, result);
    return result;
  }
}
