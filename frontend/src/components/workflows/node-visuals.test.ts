import {
  ArrowUpDown,
  Bot,
  Code2,
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
  groupVisual,
  nodeVisual,
  operationRank,
  operationVisual,
} from "./node-visuals";

describe("nodeVisual", () => {
  it("names a step by its own id first, then by what it touches", () => {
    expect(nodeVisual("logic.if", "logic").icon).toBe(GitBranch);
    expect(nodeVisual("agent.run", "agent").icon).toBe(Bot);
    expect(nodeVisual("table.record.get", "tables").icon).toBe(Table2);
    expect(nodeVisual("http.download", "http").icon).toBe(Download);
    expect(nodeVisual("future.file.step", "files").icon).toBe(File);
    expect(nodeVisual("future.code.step", "code").icon).toBe(Code2);
  });

  it("draws each Transform step by what it does to the list", () => {
    expect(nodeVisual("transform.sort", "transform").icon).toBe(ArrowUpDown);
    expect(nodeVisual("webhook.respond", "core").icon).toBe(Reply);
    expect(nodeVisual("transform.crypto", "transform").icon).toBe(FingerprintPattern);
    expect(groupVisual("transform").icon).toBe(WandSparkles);
  });

  it("keeps every tile neutral but an error step's", () => {
    expect(nodeVisual("code.python.simple", "code").tileClass).toContain("bg-muted");
    expect(nodeVisual("error.raise", "error").tileClass).toContain("destructive");
  });

  it("falls back to a neutral step for anything it does not know", () => {
    const visual = nodeVisual("custom.thing", "custom");
    expect(visual.icon).toBe(Zap);
    expect(visual.tileClass).toContain("bg-muted");
    expect(groupVisual("custom").icon).toBe(Zap);
    expect(operationVisual("custom.thing", "custom").icon).toBe(Zap);
  });

  it("draws a platform step with its platform's mark, and by what it does in its group", () => {
    const mark = groupVisual("slack").icon;
    expect(nodeVisual("slack.message.send", "slack").icon).toBe(mark);
    expect(operationVisual("slack.message.send", "slack").icon).toBe(Send);
    expect(operationVisual("slack.channels.find", "slack").icon).toBe(Search);
    expect(operationVisual("slack.something.new", "slack").icon).toBe(Zap);
    expect(operationVisual("http.download", "http").icon).toBe(Download);
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
