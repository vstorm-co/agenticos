import { describe, expect, it } from "vitest";
import { buildWikiGraph, parseWikiPage, wikiPath, WIKI_RELATION_LIMITS } from "./wiki-graph";
import { layoutWiki } from "./wiki-layout";

describe("wiki document relationships", () => {
  it("reads metadata and real links, excluding code, comments, URLs and same-page anchors", () => {
    const page = parseWikiPage(
      "notes/a.md",
      `---
title: Topic A
aliases: [Alpha, 12]
tags: [research, '#ai']
related: ['[[Beta]]', 'notes/c.md', 3]
sources: ['https://example.com', 'sources/report.md']
links: notes/d.md
---
# Heading
[[Beta#Section|label]] [C](c.md "title") [space](<space%20name.md>)
[Web](https://example.com) [anchor](#heading) [bad](bad%ZZ) [encoded](https%3A%2F%2Fx.test)
![[image.png]]
\`[[inline]]\`
<!-- [[comment]] -->
\`\`\`md
[[example]]
\`\`\`
~~~
[[other example]]
~~~
`,
    );
    expect(page.title).toBe("Topic A");
    expect(page.aliases).toEqual(["Alpha"]);
    expect(page.tags).toEqual(["research", "ai"]);
    expect(page.invalidFrontmatter).toBe(false);
    expect(page.links.map((link) => link.target)).toEqual([
      "Beta",
      "image.png",
      "c.md",
      "space name.md",
      "notes/d.md",
      "Beta",
      "notes/c.md",
      "sources/report.md",
    ]);
  });

  it("handles BOM, CRLF, malformed YAML, YAML aliases and scalar frontmatter", () => {
    expect(parseWikiPage("a.md", "\uFEFF---\r\ntitle: Hello\r\n...\r\n# Other").title).toBe(
      "Hello",
    );
    for (const header of ["title: [broken", "title: A\ntitle: B", "a: &x [value]\nb: *x"]) {
      const page = parseWikiPage("a.md", `---\n${header}\n---\n# Body\n[[Other]]`);
      expect(page.invalidFrontmatter).toBe(true);
      expect(page.title).toBe("Body");
      expect(page.links).toHaveLength(1);
    }
    expect(parseWikiPage("a.md", "---\n42\n---\nbody").title).toBe("a");
    expect(parseWikiPage("a.md", "---\n- list\n---\nbody").aliases).toEqual([]);
    expect(parseWikiPage("", "").title).toBe("");
    expect(parseWikiPage("a.md", "---\ntitle: ''\ntags: '#one #two'\n---\n").tags).toEqual([
      "one",
      "two",
    ]);
  });

  it("resolves relative Markdown paths, root wiki paths, aliases and backlinks without guessing duplicates", () => {
    const graph = buildWikiGraph([
      parseWikiPage(
        "notes/a.md",
        "[[Beta]] [[Duplicate]] [[Absent]] [[a]] [B](b.md) [root](/root.md) [escape](../../secret.md) [[notes/b]] [[root]]",
      ),
      parseWikiPage("notes/b.md", "---\ntitle: Second\naliases: Beta\n---\n[[notes/a]]"),
      parseWikiPage("x/d.md", "# Duplicate"),
      parseWikiPage("y/d.md", "# Duplicate"),
      parseWikiPage("root.md", "# Root"),
    ]);
    expect(graph.edges).toEqual([
      { source: "notes/a.md", target: "notes/b.md" },
      { source: "notes/a.md", target: "root.md" },
      { source: "notes/b.md", target: "notes/a.md" },
    ]);
    expect(graph.unresolved).toEqual([
      { source: "notes/a.md", target: "Duplicate", reason: "ambiguous" },
      { source: "notes/a.md", target: "Absent", reason: "missing" },
      { source: "notes/a.md", target: "../../secret.md", reason: "missing" },
    ]);
  });

  it("never matches arbitrary Markdown targets by a wiki alias or silently folds path case", () => {
    const graph = buildWikiGraph([
      parseWikiPage(
        "a.md",
        "[alias](Alias) [[NOTES/b]] [[Alias]] [[//host/file]] [[javascript:alert]] [[%2F%2Fhost]] [[/b]]",
      ),
      parseWikiPage("notes/b.md", "---\naliases: Alias\n---\n"),
    ]);
    expect(graph.edges).toEqual([{ source: "a.md", target: "notes/b.md" }]);
    expect(graph.unresolved.map((link) => link.target)).toEqual(["NOTES/b", "/b", "Alias"]);
  });

  it("keeps missing relationships after a linked note is deleted or renamed", () => {
    const a = parseWikiPage("a.md", "[[b]] [[b]]"),
      b = parseWikiPage("b.md", "");
    expect(buildWikiGraph([a, b]).edges).toHaveLength(1);
    expect(buildWikiGraph([a]).unresolved).toHaveLength(1);
    expect(buildWikiGraph([a, parseWikiPage("c.md", "")]).edges).toHaveLength(0);
  });

  it("normalizes only workspace paths and refuses traversal above root", () => {
    expect(wikiPath("/notes/./a/../b.md")).toBe("notes/b.md");
    expect(wikiPath("notes\\b.md")).toBe("notes/b.md");
    expect(wikiPath("../a.md")).toBeNull();
    const graph = buildWikiGraph([parseWikiPage("../a.md", "[[b]]"), parseWikiPage("b.md", "")]);
    expect(graph.pages).toHaveLength(2);
  });

  it("lays out connected and isolated notes deterministically inside the canvas", () => {
    expect(layoutWiki(buildWikiGraph([])).size).toBe(0);
    const graph = buildWikiGraph([
      parseWikiPage("a.md", "[[b]]"),
      parseWikiPage("b.md", ""),
      parseWikiPage("c.md", ""),
    ]);
    const first = layoutWiki(graph);
    expect(first).toEqual(layoutWiki(graph));
    expect(new Set([...first.values()].map(({ x, y }) => `${x},${y}`)).size).toBe(3);
    for (const { x, y } of first.values()) {
      expect(Number.isFinite(x)).toBe(true);
      expect(Number.isFinite(y)).toBe(true);
    }
    expect(
      layoutWiki({
        ...graph,
        edges: [
          ...graph.edges,
          { source: "deleted", target: "a.md" },
          { source: "a.md", target: "deleted" },
        ],
      }),
    ).toEqual(first);
  });
});

it.each([
  "   ```md\n[[hidden]]\n   ````\n[[shown]]",
  "  ~~~md\n[[hidden]]\n~~~~~\n[[shown]]",
  "```md\n[[hidden]]\n```not-a-close\n[[also hidden]]",
  "~~~\n[[hidden]]",
])("respects indented, longer and unclosed Markdown fences: %s", (body) => {
  expect(parseWikiPage("a.md", body).links.map((link) => link.target)).toEqual(
    body.includes("[[shown]]") ? ["shown"] : [],
  );
});

it("keeps inline code delimiters exact and comments out of relationships", () => {
  const page = parseWikiPage(
    "a.md",
    "`` [[hidden]] ` <!-- `` [[shown]] <!-- [[comment]] --> [[last]]",
  );
  expect(page.links.map((link) => link.target)).toEqual(["shown", "last"]);
});

it("handles adversarial backticks, brackets and unclosed comments without backtracking", () => {
  for (const prefix of ["`".repeat(200_000), "[".repeat(200_000), "<!--".repeat(50_000)]) {
    const page = parseWikiPage("a.md", prefix + "\n[[visible]]");
    expect(page.links).toHaveLength(prefix.startsWith("<!--") || prefix.startsWith("```") ? 0 : 1);
  }
});

it("bounds relationships from body and frontmatter and reports exactly what was omitted", () => {
  const many = Array.from({ length: WIKI_RELATION_LIMITS.page + 1 }, (_, i) => `[[target${i}]]`);
  const page = parseWikiPage("a.md", many.join(" "));
  expect(page.links).toHaveLength(WIKI_RELATION_LIMITS.page);
  expect(page.linksTruncated).toBe(true);
  expect(parseWikiPage("a.md", many.slice(0, -1).join(" ")).linksTruncated).toBe(false);
  const frontmatter = parseWikiPage("a.md", `---\nrelated: ${JSON.stringify(many)}\n---`);
  expect(frontmatter.links).toHaveLength(WIKI_RELATION_LIMITS.page);
  expect(frontmatter.linksTruncated).toBe(true);
  const pages = Array.from({ length: 12 }, (_, i) => parseWikiPage(`${i}.md`, many.join(" ")));
  const graph = buildWikiGraph(pages);
  expect(graph.edges.length + graph.unresolved.length).toBe(WIKI_RELATION_LIMITS.graph);
  expect(graph.relationshipsTruncated).toBe(true);
});

it("leaves unmatched and escaped backticks as prose without hiding later links", () => {
  for (const prefix of ["text ` unmatched", "text \\` escaped"]) {
    expect(parseWikiPage("a.md", prefix + " [[a]]").links.map((link) => link.target)).toEqual([
      "a",
    ]);
  }
});

it("bounds Markdown relationships as well as wikilinks", () => {
  const body = Array.from(
    { length: WIKI_RELATION_LIMITS.page + 1 },
    (_, i) => `[note](${i}.md)`,
  ).join(" ");
  const page = parseWikiPage("a.md", body);
  expect(page.links).toHaveLength(WIKI_RELATION_LIMITS.page);
  expect(page.linksTruncated).toBe(true);
});

it("ignores escaped links but permits links after an escaped backslash", () => {
  const page = parseWikiPage(
    "a.md",
    String.raw`\[[draft]] \[label](draft.md) \\[[real]] [[visible]]`,
  );
  expect(page.links.map((link) => link.target)).toEqual(["real", "visible"]);
});

it("consumes malformed destination tails once and still parses balanced links", () => {
  const page = parseWikiPage("a.md", "[](".repeat(80_000));
  expect(page.links).toHaveLength(0);
  const valid = parseWikiPage("a.md", "[A](notes/a(1).md \"Title\") [B](<b.md> 'Title')");
  expect(valid.links.map((link) => link.target)).toEqual(["notes/a(1).md", "b.md"]);
});

it("caps frontmatter aliases and tags before indexing, and marks lost metadata", () => {
  const values = Array.from({ length: 5000 }, (_, i) => `alias${i}`);
  const page = parseWikiPage(
    "a.md",
    `---\naliases: ${JSON.stringify(values)}\ntags: research\n---`,
  );
  expect(page.aliases).toHaveLength(128);
  expect(page.tags).toHaveLength(0);
  expect(page.metadataTruncated).toBe(true);
  const tags = parseWikiPage("a.md", `---\ntags: '${values.join(" ")}'\n---`);
  expect(tags.tags).toHaveLength(128);
  expect(tags.metadataTruncated).toBe(true);
  expect(
    buildWikiGraph(Array.from({ length: 40 }, (_, i) => ({ ...page, path: `${i}.md` })))
      .metadataTruncated,
  ).toBe(true);
});

it("handles destination whitespace, escaped punctuation and optional titles", () => {
  const page = parseWikiPage(
    "a.md",
    String.raw`[A](   a\(1\).md "A \"quoted\" title"   ) [B](b.md (title)  )`,
  );
  expect(page.links.map((link) => link.target)).toEqual(["a(1).md", "b.md"]);
  for (const body of [
    "[bad](<nested<)",
    "[bad](<line\nbreak>)",
    '[bad](a.md "unclosed',
    "[bad]()",
  ]) {
    expect(parseWikiPage("a.md", body).links).toHaveLength(0);
  }
});
