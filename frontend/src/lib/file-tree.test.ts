import { describe, expect, it } from "vitest";

import { buildTree, folderPaths, type TreeFolder } from "./file-tree";

const entry = (name: string, id = name) => ({ id, name, size_bytes: 10 });

describe("buildTree", () => {
  it("puts a file with no slash at the root", () => {
    const [node] = buildTree([entry("SKILL.md")]);

    expect(node).toMatchObject({ kind: "file", path: "SKILL.md", label: "SKILL.md" });
  });

  it("drops an entry whose name is nothing but separators", () => {
    // The API returns the name as stored, and a leading or doubled slash makes
    // an empty segment. Left in, it would render as a folder with no label.
    expect(buildTree([entry("/"), entry("SKILL.md")])).toHaveLength(1);
  });

  it("turns a path into the folders it implies", () => {
    // There is no folder table: a folder is a prefix some file has, which is
    // what makes an empty one impossible.
    const [folder] = buildTree([entry("references/workflows.md")]) as [TreeFolder];

    expect(folder).toMatchObject({ kind: "folder", path: "references", label: "references" });
    expect(folder.children[0]).toMatchObject({
      kind: "file",
      path: "references/workflows.md",
      label: "workflows.md",
    });
  });

  it("puts two files in one folder rather than two folders of one name", () => {
    const [folder] = buildTree([entry("references/a.md"), entry("references/b.md")]) as [
      TreeFolder,
    ];

    expect(folder.children).toHaveLength(2);
  });

  it("nests as deep as the path goes", () => {
    const [outer] = buildTree([entry("scripts/build/run.py")]) as [TreeFolder];
    const inner = outer.children[0] as TreeFolder;

    expect(inner.path).toBe("scripts/build");
    expect(inner.children[0]).toMatchObject({ label: "run.py" });
  });

  it("sorts folders before files, each by name", () => {
    // How every file browser anybody has used behaves; a tree that sorts
    // otherwise reads as unsorted.
    const nodes = buildTree([
      entry("SKILL.md"),
      entry("scripts/run.py"),
      entry("LICENSE.txt"),
      entry("references/a.md"),
    ]);

    expect(nodes.map((node) => node.label)).toEqual([
      "references",
      "scripts",
      "LICENSE.txt",
      "SKILL.md",
    ]);
  });

  it("names every folder for expand-all", () => {
    const nodes = buildTree([entry("a/b/c.md"), entry("d/e.md")]);

    expect(folderPaths(nodes).sort()).toEqual(["a", "a/b", "d"]);
  });
});
