import { parseDocument } from "yaml";

export interface WikiPage {
  path: string;
  title: string;
  aliases: string[];
  tags: string[];
  links: { target: string; relative: boolean }[];
  invalidFrontmatter: boolean;
}

export interface WikiGraph {
  pages: WikiPage[];
  edges: { source: string; target: string }[];
  unresolved: { source: string; target: string; reason: "missing" | "ambiguous" }[];
}

function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Canonical, workspace-relative names only; never resolves a URL or leaves the root. */
export function wikiPath(path: string): string | null {
  const parts: string[] = [];
  for (const part of path.replaceAll("\\", "/").split("/")) {
    if (part === "..") {
      if (parts.length === 0) return null;
      parts.pop();
    } else if (part !== "." && part !== "") parts.push(part);
  }
  return parts.join("/");
}

function targetName(value: string): string | null {
  let name = value
    .trim()
    .replace(/^\[\[|\]\]$/g, "")
    .split("|")[0]
    ?.split("#")[0]
    ?.trim();
  if (!name || /^[a-z][a-z\d+.-]*:/i.test(name) || name.startsWith("//")) return null;
  try {
    name = decodeURIComponent(name);
  } catch {
    return null;
  }
  // Encoded schemes and separators are untrusted too. No file read uses a link target.
  return /^[a-z][a-z\d+.-]*:/i.test(name) || name.startsWith("//") ? null : name;
}

export function parseWikiPage(path: string, content: string): WikiPage {
  let body = content.replace(/^\uFEFF/, "").replaceAll("\r\n", "\n");
  let metadata: Record<string, unknown> = {};
  let invalidFrontmatter = false;
  const header = /^---\n([\s\S]*?)\n(?:---|\.\.\.)(?:\n|$)/.exec(body);
  if (header) {
    body = body.slice(header[0].length);
    try {
      const document = parseDocument(header[1] ?? "", { uniqueKeys: true });
      if (document.errors.length) invalidFrontmatter = true;
      else {
        const value: unknown = document.toJS({ maxAliasCount: 0 });
        if (isRecord(value)) metadata = value;
      }
    } catch {
      invalidFrontmatter = true;
    }
  }
  // Examples, inline code and comments do not assert relationships.
  const prose = body
    .replace(/^(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\1[^\n]*(?:\n|$)/gm, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/(`+)[\s\S]*?\1/g, "");
  const links: WikiPage["links"] = [];
  const add = (value: string | undefined, relative: boolean) => {
    const target = targetName(value ?? "");
    if (target) links.push({ target, relative });
  };
  for (const match of prose.matchAll(/!?\[\[([^\]\n]+)\]\]/g)) add(match[1], false);
  for (const match of prose.matchAll(
    /(?<!!)\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^\n]*?["'])?\s*\)/g,
  )) {
    add(match[1] ?? match[2], true);
  }
  for (const field of ["links", "related", "sources"]) {
    for (const value of strings(metadata[field])) add(value, false);
  }
  return {
    path,
    title:
      strings(metadata.title)[0] ||
      /^#\s+(.+)$/m.exec(prose)?.[1]?.trim() ||
      path.split("/").at(-1)?.replace(/\.md$/i, "") ||
      path,
    aliases: strings(metadata.aliases),
    tags: strings(metadata.tags)
      .flatMap((tag) => tag.split(/\s+/))
      .map((tag) => tag.replace(/^#/, "")),
    links,
    invalidFrontmatter,
  };
}

/** Resolve exact paths first, then unambiguous wiki names. Duplicate names stay unresolved. */
export function buildWikiGraph(pages: WikiPage[]): WikiGraph {
  const paths = new Map<string, string>();
  const names = new Map<string, Set<string>>();
  const key = (name: string) => name.normalize("NFC").toLowerCase().replace(/\.md$/i, "");
  for (const page of pages) {
    const path = wikiPath(page.path);
    if (path === null) continue;
    paths.set(path, page.path);
    for (const name of [path.replace(/^.*\//, ""), page.title, ...page.aliases]) {
      const matches = names.get(key(name)) ?? new Set<string>();
      matches.add(page.path);
      names.set(key(name), matches);
    }
  }
  const exact = (path: string | null) =>
    path === null ? undefined : (paths.get(path) ?? paths.get(`${path}.md`));
  const edges = new Map<string, WikiGraph["edges"][number]>();
  const unresolved = new Map<string, WikiGraph["unresolved"][number]>();
  for (const page of pages) {
    const parent = wikiPath(page.path)?.split("/").slice(0, -1).join("/") ?? "";
    for (const link of page.links) {
      const root = wikiPath(link.target);
      const local = wikiPath(`${parent}/${link.target}`);
      // Markdown is relative to its document; wiki links prefer vault-root paths.
      let target = link.target.startsWith("/")
        ? exact(root)
        : link.relative
          ? exact(local)
          : (exact(root) ?? exact(local));
      const candidates =
        !link.relative && !link.target.includes("/") ? names.get(key(link.target)) : undefined;
      if (!target && candidates?.size === 1) target = candidates.values().next().value;
      if (target) {
        if (target !== page.path)
          edges.set(JSON.stringify([page.path, target]), { source: page.path, target });
      } else {
        unresolved.set(JSON.stringify([page.path, link.target]), {
          source: page.path,
          target: link.target,
          reason: candidates && candidates.size > 1 ? "ambiguous" : "missing",
        });
      }
    }
  }
  return { pages, edges: [...edges.values()], unresolved: [...unresolved.values()] };
}
