import { parseDocument } from "yaml";

export interface WikiPage {
  path: string;
  title: string;
  aliases: string[];
  tags: string[];
  links: { target: string; relative: boolean }[];
  invalidFrontmatter: boolean;
  linksTruncated: boolean;
}

export interface WikiGraph {
  pages: WikiPage[];
  relationshipsTruncated: boolean;
  edges: { source: string; target: string }[];
  unresolved: { source: string; target: string; reason: "missing" | "ambiguous" }[];
}

export const WIKI_RELATION_LIMITS = { page: 256, graph: 2048 } as const;

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

/** Strip examples in bounded passes; backreference regexes can retry at every backtick. */
function relationshipProse(body: string): string {
  let fence: { marker: string; length: number } | null = null;
  const lines: string[] = [];
  for (const line of body.split("\n")) {
    const delimiter = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence) {
      if (
        delimiter &&
        delimiter[1]?.[0] === fence.marker &&
        delimiter[1].length >= fence.length &&
        !delimiter[2]?.trim()
      )
        fence = null;
      lines.push("");
    } else if (delimiter && !(delimiter[1]?.[0] === "`" && delimiter[2]?.includes("`"))) {
      fence = { marker: delimiter[1]?.[0] ?? "", length: delimiter[1]?.length ?? 0 };
      lines.push("");
    } else lines.push(line);
  }
  const text = lines.join("\n");
  const nextRun = new Map<number, number>();
  const lastByLength = new Map<number, number>();
  const runs = [...text.matchAll(/`+/g)];
  for (const run of runs.reverse()) {
    const next = lastByLength.get(run[0].length);
    if (next !== undefined) nextRun.set(run.index, next + run[0].length);
    lastByLength.set(run[0].length, run.index);
  }
  const parts: string[] = [];
  let kept = 0;
  for (let i = 0; i < text.length;) {
    let end: number | undefined;
    if (text.startsWith("<!--", i)) {
      const close = text.indexOf("-->", i + 4);
      end = close < 0 ? text.length : close + 3;
    } else if (text[i] === "`") {
      end = nextRun.get(i);
      if (end === undefined) {
        do {
          i++;
        } while (text[i] === "`");
        continue;
      }
    } else if (text[i] === "\\") {
      i += 2;
      continue;
    }
    if (end !== undefined) {
      parts.push(text.slice(kept, i), "\n");
      kept = end;
      i = end;
    } else i++;
  }
  parts.push(text.slice(kept));
  return parts.join("");
}

export function parseWikiPage(
  path: string,
  content: string,
  linkBudget: number = WIKI_RELATION_LIMITS.page,
): WikiPage {
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
  const prose = relationshipProse(body);
  const links: WikiPage["links"] = [];
  const limit = Math.min(WIKI_RELATION_LIMITS.page, Math.max(0, linkBudget));
  let linksTruncated = false;
  const add = (value: string | undefined, relative: boolean): boolean => {
    const target = targetName(value ?? "");
    if (target) {
      if (links.length === limit) {
        linksTruncated = true;
        return false;
      }
      links.push({ target, relative });
    }
    return true;
  };
  for (const match of prose.matchAll(/!?\[\[([^\]\n]*)/g)) {
    const end = match.index + match[0].length;
    if (prose.startsWith("]]", end) && !add(match[1], false)) break;
  }
  const destination = /\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^\n]*?["'])?\s*\)/y;
  if (!linksTruncated)
    for (const match of prose.matchAll(/(!?)\[([^\]\n]*)/g)) {
      const end = match.index + match[0].length;
      if (match[1] || prose[end] !== "]") continue;
      destination.lastIndex = end + 1;
      const target = destination.exec(prose);
      if (target && !add(target[1] ?? target[2], true)) break;
    }
  if (!linksTruncated)
    outer: for (const field of ["links", "related", "sources"]) {
      for (const value of strings(metadata[field])) {
        if (!add(value, false)) break outer;
      }
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
    linksTruncated,
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
  let remaining = WIKI_RELATION_LIMITS.graph as number;
  let relationshipsTruncated = pages.some((page) => page.linksTruncated);
  for (const page of pages) {
    const parent = wikiPath(page.path)?.split("/").slice(0, -1).join("/") ?? "";
    for (const link of page.links) {
      if (remaining === 0) {
        relationshipsTruncated = true;
        break;
      }
      remaining--;
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
  return {
    pages,
    relationshipsTruncated,
    edges: [...edges.values()],
    unresolved: [...unresolved.values()],
  };
}
