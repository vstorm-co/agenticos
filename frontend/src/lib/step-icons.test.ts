import {
  CalendarClock,
  Bot,
  NotebookText,
  BookOpen,
  Brain,
  FolderKanban,
  ListTodo,
  Plug,
  Radar,
  Table2,
} from "lucide-react";
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

  it("keeps platform routine, agent, context and skill actions distinguishable", () => {
    expect(toolIcon("agenticos_create_routine")).toBe(CalendarClock);
    expect(toolIcon("agenticos_get_agent")).toBe(Bot);
    expect(toolIcon("agenticos_read_context")).toBe(NotebookText);
    expect(toolIcon("agenticos_load_skill")).toBe(BookOpen);
    expect(toolIcon("agenticos_other_action", "mcp")).toBe(Plug);
  });

  it("does not guess another service's identity from an operation name", () => {
    expect(toolIcon("external_create_task", "mcp")).toBe(Plug);
  });
});

it.each([
  "agenticos_get_document",
  "agenticos_read_file",
  "agenticos_create_folder",
  "agenticos_create_app",
  "agenticos_get_workflow",
  "agenticos_list_members",
  "agenticos_get_channel",
  "agenticos_list_inbox_cases",
  "agenticos_get_secret",
  "agenticos_search_mcp_servers",
])("uses an object icon for %s instead of a generic MCP plug", (name) => {
  expect(toolIcon(name, "mcp")).not.toBe(Plug);
});
