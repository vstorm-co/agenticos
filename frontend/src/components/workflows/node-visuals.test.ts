import { Bot, Code2, Download, File, GitBranch, Table2, Zap } from "lucide-react";
import { describe, expect, it } from "vitest";

import { CATEGORY_ORDER, categoryRank, nodeVisual } from "./node-visuals";

describe("nodeVisual", () => {
  it("names a step by its own id first, then by what it touches", () => {
    expect(nodeVisual("logic.if", "logic").icon).toBe(GitBranch);
    expect(nodeVisual("agent.run", "agent").icon).toBe(Bot);
    expect(nodeVisual("table.record.get", "tables").icon).toBe(Table2);
    expect(nodeVisual("http.download", "http").icon).toBe(Download);
    expect(nodeVisual("code.python.simple", "code").tileClass).toContain("indigo");
    expect(nodeVisual("future.file.step", "files").icon).toBe(File);
    expect(nodeVisual("future.code.step", "code").icon).toBe(Code2);
  });

  it("falls back to a neutral step for anything it does not know", () => {
    const visual = nodeVisual("custom.thing", "custom");
    expect(visual.icon).toBe(Zap);
    expect(visual.tileClass).toContain("bg-muted");
  });
});

describe("categoryRank", () => {
  it("orders groups the way a workflow reads, and an unknown one last", () => {
    expect(categoryRank("triggers")).toBe(0);
    expect(categoryRank("core")).toBe(1);
    expect(categoryRank("tables")).toBeLessThan(categoryRank("error"));
    expect(categoryRank("files")).toBeLessThan(categoryRank("code"));
    expect(categoryRank("custom")).toBe(CATEGORY_ORDER.length);
  });
});
