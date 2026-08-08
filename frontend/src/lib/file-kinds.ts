/**
 * What kind of file this is, answered once.
 *
 * There were three answers to this question - `resolveViewerKind` for a knowledge
 * base document, `previewKind` for an attachment in the composer, and the
 * `isTextual`/`isMarkdown` pair for a workspace file - and two icon sets built on
 * two of them. Three tables of suffixes drift the moment one is edited, and they
 * had: a `.csv` an agent wrote was a spreadsheet to the icon, plain text to the
 * viewer and a table to the composer's card, all on the same screen.
 *
 * One kind, and every consumer reads it off this: which request to make, which
 * viewer renders, and which mark a listing draws.
 */

/**
 * What a file is, at the granularity anything here acts on.
 *
 * Each entry changes at least one of three decisions, which is what keeps the list
 * from growing into a taxonomy: whether the file is fetched as text or as bytes,
 * which viewer renders it, and which icon a listing shows. `spreadsheet` and
 * `document` are the binary office formats - a `.xlsx` is not a `.csv` and must
 * never be parsed as one - and they are here because an icon can say what they are
 * even though no viewer can show them.
 */
export type FileKind =
  // Rendered from bytes, and only when the server agrees to type them.
  | "image"
  | "pdf"
  | "video"
  | "audio"
  // Rendered from characters.
  | "markdown"
  | "html"
  | "csv"
  | "json"
  | "code"
  | "text"
  // Known, and not showable. An icon, a size, and a download.
  | "spreadsheet"
  | "document"
  | "archive"
  | "unknown";

/** The suffix, lowercased, without the dot. Empty for a file that has none. */
export function suffixOf(path: string): string {
  const name = path.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

const BY_SUFFIX: Record<string, FileKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  bmp: "image",
  ico: "image",
  avif: "image",
  tiff: "image",
  pdf: "pdf",
  mp4: "video",
  webm: "video",
  mov: "video",
  m4v: "video",
  ogv: "video",
  mkv: "video",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  oga: "audio",
  m4a: "audio",
  flac: "audio",
  opus: "audio",
  aac: "audio",
  weba: "audio",
  md: "markdown",
  markdown: "markdown",
  mdx: "markdown",
  html: "html",
  htm: "html",
  csv: "csv",
  tsv: "csv",
  json: "json",
  jsonc: "json",
  jsonl: "json",
  xlsx: "spreadsheet",
  xls: "spreadsheet",
  ods: "spreadsheet",
  docx: "document",
  doc: "document",
  odt: "document",
  rtf: "document",
  pptx: "document",
  epub: "document",
  zip: "archive",
  tar: "archive",
  gz: "archive",
  tgz: "archive",
  bz2: "archive",
  xz: "archive",
  rar: "archive",
  "7z": "archive",
  txt: "text",
  log: "text",
  env: "text",
  conf: "text",
  cfg: "text",
  ini: "text",
  gitignore: "text",
  dockerignore: "text",
};

/**
 * Suffix to the language slug `rehype-highlight` knows it by.
 *
 * Doubles as the list of what counts as code: a suffix in here is `code` and gets
 * fenced with its language, which is how a source file is highlighted without a
 * second highlighter being imported.
 */
const CODE_LANGUAGES: Record<string, string> = {
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  hpp: "cpp",
  cs: "csharp",
  php: "php",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  fish: "bash",
  ps1: "powershell",
  sql: "sql",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  xml: "xml",
  // Markup rather than a picture. An SVG is the one image whose bytes are a
  // document with script in it, which is why the API refuses to serve one inline -
  // so the useful and safe thing to show is its source, fenced.
  svg: "xml",
  graphql: "graphql",
  gql: "graphql",
  proto: "protobuf",
  dockerfile: "dockerfile",
  makefile: "makefile",
  scala: "scala",
  lua: "lua",
  vue: "vue",
  svelte: "svelte",
  r: "r",
  jl: "julia",
  ex: "elixir",
  exs: "elixir",
  erl: "erlang",
  elm: "elm",
  hs: "haskell",
  ml: "ocaml",
  fs: "fsharp",
  pl: "perl",
  scss: "scss",
  sass: "scss",
  less: "less",
  css: "css",
  diff: "diff",
  patch: "diff",
};

/** The language a code file is fenced with, or `text` when nobody mapped it. */
export function codeLanguage(name: string): string {
  return CODE_LANGUAGES[suffixOf(name)] ?? "text";
}

/**
 * What this file is, from its name and whatever type came with it.
 *
 * The media type wins where it says something specific, because a name is a
 * suggestion and a stored `filetype` is what the server actually read. It loses
 * where it says nothing - `application/octet-stream` is what a browser sends for
 * every drag-and-drop of a type it does not recognise, and the name is then the
 * only clue there is.
 *
 * An unknown suffix and no useful type is `unknown`, which asks for bytes. That is
 * the safe way round: a text file arrives as an offered download, where guessing the
 * other way renders a binary as mojibake.
 */
export function resolveFileKind(name: string, mimeType?: string | null): FileKind {
  const suffix = suffixOf(name);
  const mime = (mimeType ?? "").toLowerCase().split(";")[0]?.trim() ?? "";

  // Before the `image/` check below, and deliberately: `image/svg+xml` is markup.
  if (suffix === "svg" || mime === "image/svg+xml") return "code";

  const declared = fromMediaType(mime);
  if (declared !== null) return declared;

  const known = BY_SUFFIX[suffix];
  if (known !== undefined) return known;
  if (CODE_LANGUAGES[suffix] !== undefined) return "code";

  // Last, so a specific suffix is never overruled by a type as broad as `text/*`.
  if (mime.startsWith("text/")) return "text";
  return "unknown";
}

/** What a media type says on its own, or null when it says nothing specific. */
function fromMediaType(mime: string): FileKind | null {
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (mime === "text/html") return "html";
  if (mime === "text/markdown") return "markdown";
  if (mime === "text/csv" || mime === "text/tab-separated-values") return "csv";
  if (mime === "application/json") return "json";
  if (mime === "application/javascript" || mime === "application/xml") return "code";
  if (mime === "application/x-yaml" || mime === "application/yaml") return "code";
  if (mime === "application/zip" || mime === "application/gzip") return "archive";
  return null;
}

const TEXT_KINDS: ReadonlySet<FileKind> = new Set<FileKind>([
  "markdown",
  "html",
  "csv",
  "json",
  "code",
  "text",
]);

/**
 * Whether to ask for this file's characters rather than its bytes.
 *
 * It decides which *request* is made and nothing else. Whether what came back can
 * be displayed is the server's answer, read off the response's type: the API decides
 * what may be shown inline - raster images and PDFs, never SVG or HTML, because
 * either served inline from this origin is stored XSS with the agent as its author -
 * and a second list of suffixes making that call here would be a second answer that
 * drifts the first time either moves.
 */
export function readsAsText(kind: FileKind): boolean {
  return TEXT_KINDS.has(kind);
}

const TRANSFORMED_KINDS: ReadonlySet<FileKind> = new Set<FileKind>([
  "markdown",
  "html",
  "csv",
  "json",
]);

/**
 * Whether a rendered view and the characters are two different things worth having.
 *
 * Both are the file. An agent writing a report means the prose; an agent writing a
 * prompt or a spec means the characters it will be read back as - and a `#` that
 * silently became large type is how somebody fails to notice their agent is writing
 * Markdown into a file nothing reads as Markdown. The same holds wherever the
 * preview *transforms*: a table hides which delimiter a CSV used, a rendered page
 * hides the tag that produced it, and pretty-printed JSON is not the bytes on disk.
 *
 * Not `code`: fencing it adds colour and takes nothing away, so a source toggle
 * would offer the same characters twice.
 */
export function hasSourceView(kind: FileKind): boolean {
  return TRANSFORMED_KINDS.has(kind);
}
