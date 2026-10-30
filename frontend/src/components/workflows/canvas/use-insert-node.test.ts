import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, node, port } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useInsertNode } from "./use-insert-node";

const mayManage = vi.fn(() => true);
const channelBots = vi.fn((_enabled: boolean) => ({
  bots: [{ id: "b1", platform: "slack" }],
  isLoading: false,
  error: null as unknown,
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => mayManage() }),
  useChannelBots: (enabled: boolean) => channelBots(enabled),
}));

const STEP = makeDefinition({
  id: "step",
  ports: [port("in", "input", null), port("out", "output", null)],
});

const REAL_INSERT = useWorkflowEditorStore.getState().insertNode;

beforeEach(() => {
  mayManage.mockReturnValue(true);
  channelBots.mockReturnValue({
    bots: [{ id: "b1", platform: "slack" }],
    isLoading: false,
    error: null,
  });
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

const CHANNEL = makeDefinition({
  id: "trigger.channel_message",
  ports: [port("out", "output", null)],
});
const SLACK_SEND = makeDefinition({
  id: "slack.message.send",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const TELEGRAM_SEND = makeDefinition({
  id: "telegram.message.send",
  ports: [port("in", "input", null), port("out", "output", null)],
});

function seedChannel(config: Record<string, unknown> = { bot_id: "b1" }, wired = true) {
  const nodes = wired
    ? [node("t", "trigger.channel_message", config)]
    : [node("t", "trigger.channel_message", config), node("a", "mcp.call")];
  useWorkflowEditorStore.getState().seedGraph({
    entry_node_id: "t",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  });
}

function addSend(
  definition: typeof SLACK_SEND,
  options: { config?: Record<string, unknown>; from?: string } = { from: "t" },
) {
  const { result } = renderHook(() =>
    useInsertNode([CHANNEL, SLACK_SEND, TELEGRAM_SEND, MCP_CALL]),
  );
  result.current(definition, {
    config: options.config,
    from: options.from === undefined ? undefined : { nodeId: options.from, portId: "out" },
  });
  const graph = useWorkflowEditorStore.getState().graph;
  const added = graph?.nodes.find((item) => item.definition_id === definition.id);
  return {
    graph,
    added,
    wired: graph?.bindings
      .filter((binding) => binding.target_node_id === added?.id)
      .map((binding) => [
        binding.target_field,
        binding.source.kind === "node_output" ? binding.source.field_path.join("/") : null,
      ]),
  };
}

it("starts Send a message after a channel trigger as the trigger's bot, answering where the message came from", () => {
  seedChannel();
  const { added, wired } = addSend(SLACK_SEND);
  expect(added?.config).toEqual({ bot_id: "b1" });
  expect(wired).toEqual([
    ["channel_id", "channel_id"],
    ["thread_id", "thread_id"],
  ]);

  useWorkflowEditorStore.getState().undo();
  const undone = useWorkflowEditorStore.getState().graph;
  expect(undone?.nodes.map((item) => item.id)).toEqual(["t"]);
  expect(undone?.bindings).toEqual([]);
});

it("suggests nothing when the trigger's bot is of another platform", () => {
  seedChannel();
  const { added, wired } = addSend(TELEGRAM_SEND);
  expect(added?.config).toEqual({});
  expect(wired).toEqual([]);
});

it.each([
  [
    "while the bots load",
    () => channelBots.mockReturnValue({ bots: [], isLoading: true, error: null }),
  ],
  [
    "after they fail",
    () =>
      channelBots.mockReturnValue({
        bots: [{ id: "b1", platform: "slack" }],
        isLoading: false,
        error: new Error("boom"),
      }),
  ],
  ["without channels:manage", () => mayManage.mockReturnValue(false)],
])("suggests nothing %s", (_case, arrange) => {
  seedChannel();
  arrange();
  const { added, wired } = addSend(SLACK_SEND);
  expect(added?.config).toEqual({});
  expect(wired).toEqual([]);
});

it("asks for the bots only for a member who may manage them", () => {
  seedChannel();
  mayManage.mockReturnValue(false);
  addSend(SLACK_SEND);
  expect(channelBots).toHaveBeenCalledWith(false);
});

it("suggests nothing when the trigger names no bot, names an unknown one, or is not upstream", () => {
  seedChannel({});
  expect(addSend(SLACK_SEND).added?.config).toEqual({});
  useWorkflowEditorStore.getState().teardown();
  seedChannel({ bot_id: "gone" });
  expect(addSend(SLACK_SEND).wired).toEqual([]);
  useWorkflowEditorStore.getState().teardown();
  seedChannel({ bot_id: "b1" }, false);
  const unwired = addSend(SLACK_SEND, { from: "a" });
  expect(unwired.added?.config).toEqual({});
  expect(unwired.wired).toEqual([]);
});

it("suggests nothing for a step that is not Send a message", () => {
  seedChannel();
  const { result } = renderHook(() => useInsertNode([CHANNEL, MCP_CALL]));
  result.current(MCP_CALL, { from: { nodeId: "t", portId: "out" } });
  expect(useWorkflowEditorStore.getState().graph?.bindings).toEqual([]);
});

it("keeps a bot the step was added with, and still binds the reply", () => {
  seedChannel();
  const { added, wired } = addSend(SLACK_SEND, { config: { bot_id: "b9" }, from: "t" });
  expect(added?.config).toEqual({ bot_id: "b9" });
  expect(wired).toEqual([
    ["channel_id", "channel_id"],
    ["thread_id", "thread_id"],
  ]);
});

it("does not fetch the channel bots for a read-only canvas", () => {
  channelBots.mockClear();
  renderHook(() => useInsertNode([STEP], true));
  expect(channelBots).toHaveBeenCalledWith(false);
  channelBots.mockClear();
  renderHook(() => useInsertNode([STEP], false));
  expect(channelBots).toHaveBeenCalledWith(true);
});

it("renames a merge's branches when a step is put into the wire of one", () => {
  const insertNode = vi.fn();
  const IN = port("in", "input", null);
  const OUT = port("out", "output", null);
  const catalog = [
    STEP,
    makeDefinition({ id: "logic.split", kind: "control", ports: [IN] }),
    makeDefinition({ id: "logic.merge", kind: "control", ports: [IN, OUT] }),
  ];
  const wire = (id: string, from: string, fromPort: string, to: string) => ({
    id,
    source_node_id: from,
    source_port: fromPort,
    target_node_id: to,
    target_port: "in",
  });
  const edges = [
    wire("e0", "S", "a", "A"),
    wire("e1", "S", "b", "B"),
    wire("e2", "A", "out", "J"),
    wire("e3", "B", "out", "J"),
  ];
  useWorkflowEditorStore.setState({
    insertNode,
    graph: {
      entry_node_id: "S",
      nodes: [
        node("S", "logic.split", { branches: [{ name: "a" }, { name: "b" }] }),
        node("A", "step"),
        node("B", "step"),
        node("J", "logic.merge", {
          wait_for: "all",
          branch_keys: [{ source_node_id: "A", source_port: "out", key: "first" }],
        }),
      ],
      edges,
      bindings: [],
      scopes: [],
    },
  });
  const { result } = renderHook(() => useInsertNode(catalog));

  result.current(STEP, { between: edges[2] as (typeof edges)[number] });

  const inserted = insertNode.mock.calls[0]?.[0] as {
    node: { id: string };
    configs: Record<string, { branch_keys: { source_node_id: string; key: string }[] }>;
  };
  // The branch keeps the name its author gave it, now on the new step's wire.
  expect(inserted.configs["J"]?.branch_keys).toEqual([
    { source_node_id: "B", source_port: "out", key: expect.any(String) },
    { source_node_id: inserted.node.id, source_port: "out", key: "first" },
  ]);
});

describe("merge configs when a step is added", () => {
  const IN = port("in", "input", null);
  const OUT = port("out", "output", null);
  const catalog = [
    STEP,
    makeDefinition({ id: "logic.split", kind: "control", ports: [IN] }),
    makeDefinition({ id: "logic.merge", kind: "control", ports: [IN, OUT] }),
  ];
  const wire = (id: string, from: string, fromPort: string, to: string) => ({
    id,
    source_node_id: from,
    source_port: fromPort,
    target_node_id: to,
    target_port: "in",
  });
  const seed = (mergeConfig: Record<string, unknown>) => {
    const edges = [
      wire("e0", "S", "a", "A"),
      wire("e1", "S", "b", "B"),
      wire("e2", "A", "out", "J"),
      wire("e3", "B", "out", "J"),
      wire("e4", "J", "out", "T"),
    ];
    const insertNode = vi.fn();
    useWorkflowEditorStore.setState({
      insertNode,
      graph: {
        entry_node_id: "S",
        nodes: [
          node("S", "logic.split", { branches: [{ name: "a" }, { name: "b" }] }),
          node("A", "step"),
          node("B", "step"),
          node("J", "logic.merge", mergeConfig),
          node("T", "step"),
        ],
        edges,
        bindings: [],
        scopes: [],
      },
    });
    return { insertNode, edges };
  };
  const configsOf = (insertNode: ReturnType<typeof vi.fn>) =>
    (insertNode.mock.calls[0]?.[0] as { configs: Record<string, unknown> }).configs;

  it("changes no merge when the step is dropped on the canvas", () => {
    const { insertNode } = seed({});
    renderHook(() => useInsertNode(catalog)).result.current(STEP, { dropAt: { x: 1, y: 1 } });
    expect(configsOf(insertNode)).toEqual({});
  });

  it("changes no merge when the step is put into a wire that does not reach one", () => {
    const { insertNode, edges } = seed({});
    renderHook(() => useInsertNode(catalog)).result.current(STEP, {
      between: edges[4] as (typeof edges)[number],
    });
    expect(configsOf(insertNode)).toEqual({});
  });

  it("fits a merge that had no names stored when a step is put into one of its wires", () => {
    const { insertNode, edges } = seed({});
    renderHook(() => useInsertNode(catalog)).result.current(STEP, {
      between: edges[2] as (typeof edges)[number],
    });
    expect(configsOf(insertNode)).toEqual({
      J: { wait_for: "all", branch_keys: [expect.anything(), expect.anything()] },
    });
  });
});
