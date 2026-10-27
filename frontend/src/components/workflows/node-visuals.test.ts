import {
  ArrowUpDown,
  Bot,
  Code2,
  CodeXml,
  Diff,
  Download,
  File,
  FingerprintPattern,
  GitBranch,
  Reply,
  Search,
  Send,
  Table2,
  WandSparkles,
  Zap,
} from "lucide-react";
import { describe, expect, it } from "vitest";

import {
  CATEGORY_ORDER,
  categoryRank,
  familyLabelClass,
  groupVisual,
  nodeFamily,
  nodeVisual,
  operationRank,
  operationVisual,
  PICKER_SECTIONS,
  sectionSwatchClass,
} from "./node-visuals";

describe("nodeFamily", () => {
  it("is the picker section a category is listed in", () => {
    for (const section of PICKER_SECTIONS) {
      for (const group of section.groups) {
        // Errors are listed under Flow but drawn as their own family.
        expect(nodeFamily(group)).toBe(group === "error" ? "error" : section.id);
      }
    }
  });

  it("draws a category no section names as Flow", () => {
    expect(nodeFamily("custom")).toBe("flow");
    expect(nodeFamily("")).toBe("flow");
    expect(nodeFamily("debug")).toBe("flow");
  });
});

describe("sectionSwatchClass", () => {
  it("has a swatch for each family's section and none for the catch-all", () => {
    for (const section of PICKER_SECTIONS) {
      expect(sectionSwatchClass(section.id)).toBeDefined();
    }
    expect(sectionSwatchClass("more")).toBeUndefined();
  });
});

describe("nodeVisual", () => {
  it("names a step by its own id first, then by what it touches", () => {
    expect(nodeVisual("logic.if", "logic", "colour").icon).toBe(GitBranch);
    expect(nodeVisual("agent.run", "agent", "colour").icon).toBe(Bot);
    expect(nodeVisual("table.record.get", "tables", "colour").icon).toBe(Table2);
    expect(nodeVisual("http.download", "http", "colour").icon).toBe(Download);
    expect(nodeVisual("text.compare", "data", "colour").icon).toBe(Diff);
    expect(nodeVisual("html.parse", "data", "colour").icon).toBe(CodeXml);
    expect(nodeVisual("future.file.step", "files", "colour").icon).toBe(File);
    expect(nodeVisual("future.code.step", "code", "colour").icon).toBe(Code2);
  });

  it("draws each Transform step by what it does to the list", () => {
    expect(nodeVisual("transform.sort", "transform", "colour").icon).toBe(ArrowUpDown);
    expect(nodeVisual("webhook.respond", "core", "colour").icon).toBe(Reply);
    expect(nodeVisual("transform.crypto", "transform", "colour").icon).toBe(FingerprintPattern);
    expect(groupVisual("transform", "colour").icon).toBe(WandSparkles);
  });

  it("keeps Simple's tiles neutral but an error step's, whatever the family", () => {
    for (const [id, category] of [
      ["trigger.manual", "triggers"],
      ["agent.run", "agent"],
      ["logic.if", "logic"],
      ["code.python.simple", "code"],
      ["slack.message.send", "slack"],
      ["custom.thing", "custom"],
    ] as const) {
      expect(nodeVisual(id, category, "simple").tileClass).toBe("bg-muted text-foreground");
    }
    expect(nodeVisual("error.raise", "error", "simple").tileClass).toBe(
      "bg-destructive/10 text-destructive",
    );
    expect(groupVisual("tables", "simple").tileClass).toBe("bg-muted text-foreground");
    expect(operationVisual("slack.message.send", "slack", "simple").tileClass).toBe(
      "bg-muted text-foreground",
    );
    // The family is a fact about the step, whatever the style draws.
    expect(nodeVisual("agent.run", "agent", "simple").family).toBe("ai");
  });

  it("draws each family's tile in colour, in the stylesheet's classes", () => {
    expect(nodeVisual("trigger.manual", "triggers", "colour")).toMatchObject({
      family: "start",
      tileClass: "node-tile-start rounded-full",
    });
    expect(nodeVisual("agent.run", "agent", "colour").tileClass).toBe("node-tile-ai");
    expect(nodeVisual("table.record.get", "tables", "colour").tileClass).toBe("node-tile-data");
    expect(nodeVisual("http.download", "http", "colour").tileClass).toBe("node-tile-apps");
    expect(nodeVisual("logic.if", "logic", "colour").tileClass).toBe("bg-muted text-foreground");
    expect(nodeVisual("error.raise", "error", "colour")).toMatchObject({
      family: "error",
      tileClass: "bg-destructive/10 text-destructive",
    });
    expect(groupVisual("slack", "colour").tileClass).toBe("node-tile-apps");
    expect(operationVisual("slack.message.send", "slack", "colour").family).toBe("apps");
  });

  it("puts a trigger drawn with a brand's mark on the white tile, still round", () => {
    for (const id of ["trigger.gmail", "trigger.github"]) {
      expect(nodeVisual(id, "triggers", "colour").tileClass).toBe("node-tile-apps rounded-full");
      expect(nodeVisual(id, "triggers", "simple").tileClass).toBe("bg-muted text-foreground");
    }
  });

  it("gives a family's label its colour, and Simple's every one the same grey", () => {
    for (const family of ["start", "ai", "flow", "data", "apps", "error"] as const) {
      expect(familyLabelClass(family, "simple")).toBe("text-muted-foreground");
    }
    expect(familyLabelClass("start", "colour")).toBe("text-foreground");
    expect(familyLabelClass("ai", "colour")).toContain("--family-ai-ink");
    expect(familyLabelClass("flow", "colour")).toBe("text-muted-foreground");
    expect(familyLabelClass("data", "colour")).toContain("--family-data-ink");
    expect(familyLabelClass("apps", "colour")).toContain("--family-apps-ink");
    expect(familyLabelClass("error", "colour")).toContain("--family-error-ink");
  });

  it("gives the Outlook trigger a mark of its own", () => {
    expect(nodeVisual("trigger.outlook", "triggers", "colour").icon).not.toBe(Zap);
  });

  it("falls back to a neutral step for anything it does not know", () => {
    const visual = nodeVisual("custom.thing", "custom", "colour");
    expect(visual.icon).toBe(Zap);
    expect(visual.tileClass).toContain("bg-muted");
    expect(groupVisual("custom", "colour").icon).toBe(Zap);
    expect(operationVisual("custom.thing", "custom", "colour").icon).toBe(Zap);
  });

  it("draws a platform step with its platform's mark, and by what it does in its group", () => {
    const mark = groupVisual("slack", "colour").icon;
    expect(nodeVisual("slack.message.send", "slack", "colour").icon).toBe(mark);
    expect(operationVisual("slack.message.send", "slack", "colour").icon).toBe(Send);
    expect(operationVisual("slack.channels.find", "slack", "colour").icon).toBe(Search);
    expect(operationVisual("slack.something.new", "slack", "colour").icon).toBe(Zap);
    expect(operationVisual("http.download", "http", "colour").icon).toBe(Download);
  });
});

describe("categoryRank", () => {
  it("orders groups the way a workflow reads, and an unknown one last", () => {
    expect(categoryRank("triggers")).toBe(0);
    expect(categoryRank("agent")).toBeLessThan(categoryRank("logic"));
    expect(categoryRank("tables")).toBeLessThan(categoryRank("slack"));
    expect(categoryRank("data")).toBeLessThan(categoryRank("transform"));
    expect(categoryRank("transform")).toBeLessThan(categoryRank("files"));
    expect(categoryRank("custom")).toBe(CATEGORY_ORDER.length);
  });
});

describe("operationRank", () => {
  it("lists a platform's steps acting first, and anything else after", () => {
    expect(operationRank("slack.message.send")).toBeLessThan(operationRank("slack.messages.read"));
    expect(operationRank("slack.members.list")).toBeLessThan(operationRank("slack.channels.find"));
    expect(operationRank("table.record.get")).toBeGreaterThan(operationRank("slack.channels.find"));
  });
});
