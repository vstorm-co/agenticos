import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { makeDefinition, node, port } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useInsertNode } from "./use-insert-node";

const STEP = makeDefinition({
  id: "step",
  ports: [port("in", "input", null), port("out", "output", null)],
});

const REAL_INSERT = useWorkflowEditorStore.getState().insertNode;

beforeEach(() => {
  useWorkflowEditorStore.setState({ insertNode: REAL_INSERT });
  useWorkflowEditorStore.getState().teardown();
});

it("adds nothing before a draft is loaded, and plans the step once one is", () => {
  const insertNode = vi.fn();
  useWorkflowEditorStore.setState({ insertNode });
  const { result } = renderHook(() => useInsertNode([STEP]));

  result.current(STEP);
  expect(insertNode).not.toHaveBeenCalled();

  useWorkflowEditorStore.setState({
    graph: { entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] },
  });
  result.current(STEP, { dropAt: { x: 7, y: 8 } });
  expect(insertNode).toHaveBeenCalledWith(
    expect.objectContaining({ node: expect.objectContaining({ layout: { x: 7, y: 8 } }) }),
  );
});

it("adds a step already configured when it is given a config, as an app's action is", () => {
  const insertNode = vi.fn();
  useWorkflowEditorStore.setState({
    insertNode,
    graph: { entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] },
  });
  const { result } = renderHook(() => useInsertNode([STEP]));

  result.current(STEP, { config: { connection_id: "c1", tool: "draft_gmail_message" } });
  expect(insertNode).toHaveBeenCalledWith(
    expect.objectContaining({
      node: expect.objectContaining({
        config: { connection_id: "c1", tool: "draft_gmail_message" },
      }),
    }),
  );
});

const GMAIL = makeDefinition({
  id: "trigger.gmail",
  ports: [port("out", "output", null)],
});
const OUTLOOK = makeDefinition({
  id: "trigger.outlook",
  ports: [port("out", "output", null)],
});
const MCP_CALL = makeDefinition({
  id: "mcp.call",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const OTHER = makeDefinition({
  id: "data.map",
  ports: [port("in", "input", null), port("out", "output", null)],
});

function seed(triggerId: string | null, wired = true) {
  const nodes =
    triggerId === null
      ? [node("a", "mcp.call")]
      : wired
        ? [node("t", triggerId)]
        : [node("t", triggerId), node("a", "mcp.call")];
  useWorkflowEditorStore.getState().seedGraph({
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  });
}

function add(tool: string, from: string | undefined) {
  const { result } = renderHook(() => useInsertNode([GMAIL, OUTLOOK, MCP_CALL]));
  result.current(MCP_CALL, {
    config: { connection_id: "c1", tool },
    from: from === undefined ? undefined : { nodeId: from, portId: "out" },
  });
  return useWorkflowEditorStore.getState().graph;
}

const fields = (graph: ReturnType<typeof add>, tool: string) => {
  const added = graph?.nodes.find((item) => item.config.tool === tool);
  return graph?.bindings
    .filter((binding) => binding.target_node_id === added?.id)
    .map((binding) => [
      binding.target_field,
      binding.source.kind === "node_output" ? binding.source.field_path.join("/") : null,
    ]);
};

it("binds a Gmail draft to the trigger above it, in the same edit as the step", () => {
  seed("trigger.gmail");
  const graph = add("draft_gmail_message", "t");
  expect(fields(graph, "draft_gmail_message")).toEqual([
    ["arguments/thread_id", "thread_id"],
    ["arguments/in_reply_to", "rfc_message_id"],
  ]);
  expect(graph?.bindings[0]?.source).toMatchObject({ node_id: "t", port: "out" });

  useWorkflowEditorStore.getState().undo();
  const undone = useWorkflowEditorStore.getState().graph;
  expect(undone?.nodes.map((item) => item.id)).toEqual(["t"]);
  expect(undone?.bindings).toEqual([]);
});

it("also binds a send's recipient to the sender", () => {
  seed("trigger.gmail");
  expect(fields(add("send_gmail_message", "t"), "send_gmail_message")).toEqual([
    ["arguments/thread_id", "thread_id"],
    ["arguments/in_reply_to", "rfc_message_id"],
    ["arguments/to", "sender"],
  ]);
});

it("binds Outlook's shared-mailbox reply draft to the Outlook trigger", () => {
  seed("trigger.outlook");
  expect(
    fields(add("create-shared-mailbox-reply-draft", "t"), "create-shared-mailbox-reply-draft"),
  ).toEqual([
    ["arguments/messageId", "message_id"],
    ["arguments/userId", "mailbox"],
  ]);
});

it("binds nothing when the workflow has no such trigger", () => {
  seed(null);
  expect(add("draft_gmail_message", "a")?.bindings).toEqual([]);
});

it("binds nothing when the trigger is of another app", () => {
  seed("trigger.outlook");
  expect(add("draft_gmail_message", "t")?.bindings).toEqual([]);
});

it("binds nothing when the trigger is not upstream of the new step", () => {
  seed("trigger.gmail", false);
  expect(add("draft_gmail_message", "a")?.bindings).toEqual([]);
});

it("binds nothing for a tool with no suggestion", () => {
  seed("trigger.gmail");
  expect(add("list_gmail_labels", "t")?.bindings).toEqual([]);
});

it("binds a draft put onto an existing wire below the trigger", () => {
  useWorkflowEditorStore.getState().seedGraph({
    entry_node_id: "t",
    nodes: [node("t", "trigger.gmail"), node("next", "mcp.call")],
    edges: [
      {
        id: "e",
        source_node_id: "t",
        source_port: "out",
        target_node_id: "next",
        target_port: "in",
      },
    ],
    bindings: [],
    scopes: [],
  });
  const { result } = renderHook(() => useInsertNode([GMAIL, OUTLOOK, MCP_CALL]));
  const wire = useWorkflowEditorStore.getState().graph?.edges[0];
  result.current(MCP_CALL, {
    config: { connection_id: "c1", tool: "draft_gmail_message" },
    between: wire,
  });
  const graph = useWorkflowEditorStore.getState().graph;
  expect(fields(graph, "draft_gmail_message")).toEqual([
    ["arguments/thread_id", "thread_id"],
    ["arguments/in_reply_to", "rfc_message_id"],
  ]);
});

it("binds nothing for a step that is not an MCP call, whatever its config names", () => {
  seed("trigger.gmail");
  const { result } = renderHook(() => useInsertNode([GMAIL, OUTLOOK, MCP_CALL, OTHER]));
  result.current(OTHER, {
    config: { tool: "draft_gmail_message" },
    from: { nodeId: "t", portId: "out" },
  });
  expect(useWorkflowEditorStore.getState().graph?.bindings).toEqual([]);
});
