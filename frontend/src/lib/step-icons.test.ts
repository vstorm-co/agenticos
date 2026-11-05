import { Brain, FolderKanban, ListTodo, Plug, Radar, Table2 } from "lucide-react";
import { describe, expect, it } from "vitest";

import { toolIcon } from "./step-icons";

describe("tool object marks", () => {
  it("distinguishes platform tasks, tables, projects, watches and memory", () => {
    expect(toolIcon("agenticos_create_task")).toBe(ListTodo);
    expect(toolIcon("agenticos_query_virtual_table")).toBe(Table2);
    expect(toolIcon("agenticos_get_project")).toBe(FolderKanban);
    expect(toolIcon("agenticos_create_watch")).toBe(Radar);
    expect(toolIcon("save_memory")).toBe(Brain);
    expect(toolIcon("write_memory")).toBe(Brain);
  });

  it("does not guess another service's identity from an operation name", () => {
    expect(toolIcon("external_create_task", "mcp")).toBe(Plug);
  });
});
