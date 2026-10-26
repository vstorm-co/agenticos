import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type {
  NodeInstance,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowNodeRunRead,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NodeRunOverlayProvider, summarizeNodeRuns } from "./run-overlay";
import { WorkflowCanvas } from "./workflow-canvas";
import { nodeSummary } from "./workflow-node";

/**
 * What a node card says about its step: a line of what it is set to do, its
 * policy, its labelled ports, and - on a run's canvas - what the run did with it.
 */

vi.mock("./node-resource", async (original) => ({
  ...(await original<typeof import("./node-resource")>()),
  AgentTile: ({ agentId }: { agentId: string }) => <span>face of {agentId}</span>,
  InlineAgentTile: ({ name }: { name: string }) => <span>own face of {name}</span>,
  ResourceLine: ({ pin }: { pin: { id: string } }) => <>uses {pin.id}</>,
}));

const store = useWorkflowEditorStore;

const IO = [port("in", "input", null), port("out", "output", null)];
const CATALOG = [
  makeDefinition({
    id: "logic.if",
    name: "If",
    kind: "control",
    ports: [port("in", "input", null), port("true", "output", null), port("false", "output", null)],
  }),
  makeDefinition({ id: "http.request", name: "HTTP", ports: IO }),
  makeDefinition({ id: "error.raise", name: "Raise", ports: [port("in", "input", null)] }),
  makeDefinition({
    id: "error.handle",
    name: "Handle",
    kind: "control",
    ports: [port("in", "input", null), port("default", "output", null)],
  }),
  makeDefinition({
    id: "control.foreach",
    name: "Loop",
    kind: "control",
    ports: [port("in", "input", null), port("body", "output", null), port("done", "output", null)],
  }),
  makeDefinition({
    id: "data.map",
    name: "Map",
    category: "data",
    description: "Maps fields",
    ports: IO,
  }),
];

function instance(
  id: string,
  definitionId: string,
  extra: Partial<NodeInstance> = {},
): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: 1,
    config: {},
    layout: { x: 0, y: 0 },
    ...extra,
  };
}

const WORKFLOW: WorkflowDetail = {
  id: "wf",
  slug: "wf",
  name: "WF",
  description: null,
  status: "draft",
  visibility: "private",
  owner_user_id: null,
  current_version_id: null,
  live_trigger: null,
  tags: [],
  trigger_active: null,
  draft_revision: 0,
  entry_node: null,
  step_count: 0,
  last_run: null,
  created_at: null,
  updated_at: null,
  draft_graph: null,
  can_edit: true,
  settings: {
    timezone: "UTC",
    default_deadline_seconds: null,
    error_workflow_id: null,
    run_retention_days: null,
    keep_succeeded_runs: true,
    max_concurrent_runs: null,
    run_budget_usd: null,
    monthly_budget_usd: null,
    error_workflow_run_as: null,
  },
};

function seed(nodes: NodeInstance[], extra: Partial<WorkflowGraph> = {}): void {
  store.getState().seedGraph({
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
    ...extra,
  });
}

beforeEach(() => store.getState().teardown());

describe("a node card", () => {
  it("shows the agent a step runs as its face, and names what a step works with", () => {
    seed([
      instance("a", "data.map", { config: { agent: { agent_id: "a1", version_id: "v1" } } }),
      instance("t", "data.map", { config: { table: { table_id: "t1" } } }),
      instance("o", "data.map", { config: { inline: { name: "Lead scorer" } } }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    expect(screen.getByText("face of a1")).toBeInTheDocument();
    expect(screen.getByText("own face of Lead scorer")).toBeInTheDocument();
    expect(screen.getByText("uses a1")).toBeInTheDocument();
    expect(screen.getByText("uses t1")).toBeInTheDocument();
  });

  it("says what each kind of step is set to do", () => {
    seed([
      instance("i", "logic.if", {
        config: { condition: "value.score >= `80` || contains(value.tags || '', 'vip')" },
      }),
      instance("i2", "logic.if", { config: { condition: "length(value.tags) > `2`" } }),
      instance("h", "http.request", {
        config: { url: "https://api.example.com/x", method: "POST" },
      }),
      instance("h2", "http.request", { config: { url: "not a url" } }),
      instance("r", "error.raise", { config: { code: "REJECTED" } }),
      instance("e", "error.handle", { config: { branches: [{ name: "gone" }] } }),
      instance("f", "control.foreach", { config: { item_error_policy: "collect" } }),
      instance("m", "data.map", { config: { mappings: [{}, {}] } }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    // A condition the builder could have written reads as one; any other is shown as code.
    expect(screen.getByText("score ≥ 80 or tags contains vip")).not.toHaveClass("font-mono");
    expect(screen.getByText("length(value.tags) > `2`")).toHaveClass("font-mono");
    expect(screen.getByText("POST api.example.com")).toBeTruthy();
    expect(screen.getByText("GET not a url")).toBeTruthy();
    expect(screen.getByText("REJECTED")).toBeTruthy();
    expect(screen.getByText("1 branch and default")).toBeTruthy();
    expect(screen.getByText("Collects failed items and carries on")).toBeTruthy();
    expect(screen.getByText("2 fields")).toBeTruthy();
  });

  it("sums up a switch, a wait and a filter", () => {
    const t = ((key: string, values?: Record<string, unknown>) =>
      `${key}:${JSON.stringify(values ?? {})}`) as unknown as Parameters<typeof nodeSummary>[1];
    const summary = (definitionId: string, config: Record<string, unknown>) =>
      nodeSummary({ ...instance("x", definitionId), config }, t);
    expect(summary("logic.switch", { rules: [{}, {}] })).toBe('nodeSummaryRules:{"count":2}');
    expect(summary("logic.switch", {})).toBe('nodeSummaryRules:{"count":0}');
    expect(summary("flow.wait", { seconds: 30 })).toBe('nodeSummaryWait:{"seconds":30}');
    expect(summary("flow.wait", {})).toBeNull();
    expect(summary("flow.wait", { until_called: true, seconds: 60 })).toBe(
      "nodeSummaryWaitCall:{}",
    );
    expect(summary("data.filter", { condition: "item.ok" })).toBe("ok conditionOps.notEmpty:{}");
    expect(summary("data.filter", { condition: "!item.gone && item == 'x'" })).toBe(
      "gone conditionOps.empty:{}nodeSummaryAnd:{}item = x",
    );
    expect(summary("data.filter", {})).toBeNull();
    expect(summary("mcp.call", { tool: "find_contact" })).toBe("find_contact");
    expect(summary("mcp.call", { tool: "" })).toBeNull();
  });

  it("says what a Transform step and a schedule are set to do", () => {
    const t = ((key: string, values?: Record<string, unknown>) =>
      `${key}:${JSON.stringify(values ?? {})}`) as unknown as Parameters<typeof nodeSummary>[1];
    const summary = (definitionId: string, config: Record<string, unknown>) =>
      nodeSummary({ ...instance("x", definitionId), config }, t);

    expect(summary("transform.limit", { count: 3 })).toBe('nodeSummaryFirst:{"count":3}');
    expect(summary("transform.limit", { count: 2, from_end: true })).toBe(
      'nodeSummaryLast:{"count":2}',
    );
    expect(summary("transform.limit", {})).toBeNull();
    expect(
      summary("transform.sort", {
        by: [{ field: "score", descending: true }, { field: "name" }, "junk"],
      }),
    ).toBe('nodeSummarySort:{"fields":"score ↓, name ↑"}');
    expect(summary("transform.sort", {})).toBeNull();
    expect(summary("transform.remove_duplicates", { fields: ["email"] })).toBe(
      'nodeSummaryUniqueBy:{"fields":"email"}',
    );
    expect(summary("transform.remove_duplicates", { fields: [] })).toBe("nodeSummaryUnique:{}");
    expect(summary("transform.aggregate", { fields: ["email", ""] })).toBe(
      'nodeSummaryAggregate:{"fields":"email"}',
    );
    expect(summary("transform.aggregate", { fields: "email" })).toBeNull();
    expect(summary("transform.split_out", { field: "lines" })).toBe(
      'nodeSummarySplitOut:{"field":"lines"}',
    );
    expect(summary("transform.split_out", {})).toBeNull();
    expect(
      summary("transform.summarize", {
        summaries: [{ operation: "sum", field: "amount" }],
        group_by: ["region"],
      }),
    ).toBe(
      'nodeSummaryGrouped:{"what":"nodeSummaryOperation.sum:{\\"field\\":\\"amount\\"}","groups":"region"}',
    );
    expect(summary("transform.summarize", { summaries: [{ operation: "count" }] })).toBe(
      'nodeSummaryOperation.count:{"field":""}',
    );
    expect(summary("transform.summarize", { summaries: [] })).toBeNull();
    expect(summary("transform.edit_fields", { set: [{}, {}] })).toBe('nodeSummarySets:{"count":2}');
    expect(summary("transform.edit_fields", {})).toBeNull();
    expect(summary("transform.date_time", { operation: "add", amount: 2, unit: "hours" })).toBe(
      'nodeSummaryAdds:{"span":"nodeSummaryUnit.hours:{\\"count\\":2}"}',
    );
    expect(summary("transform.date_time", { operation: "subtract" })).toBe(
      'nodeSummarySubtracts:{"span":"nodeSummaryUnit.days:{\\"count\\":0}"}',
    );
    expect(summary("transform.date_time", { operation: "format" })).toBe("nodeSummaryFormats:{}");
    expect(summary("transform.date_time", {})).toBe("nodeSummaryNow:{}");
    expect(summary("transform.crypto", { operation: "uuid" })).toBe("nodeSummaryCrypto.uuid:{}");
    expect(summary("transform.crypto", {})).toBeNull();

    expect(summary("trigger.schedule", { schedule_kind: "interval", interval_seconds: 7200 })).toBe(
      'nodeSummaryEvery.hours:{"count":2}',
    );
    expect(
      summary("trigger.schedule", { schedule_kind: "cron", cron_expression: "30 9 * * *" }),
    ).toBe('nodeSummaryDaily:{"time":"09:30"}');
    expect(
      summary("trigger.schedule", { schedule_kind: "cron", cron_expression: "0 9 * * 1-5" }),
    ).toBe("0 9 * * 1-5");
  });

  it("sets a crontab in monospace, and names a renamed step's kind under it", () => {
    seed([
      instance("s", "trigger.schedule", {
        config: { schedule_kind: "cron", cron_expression: "0 9 * * 1-5" },
      }),
      instance("m", "data.map", { label: "Tidy the lead" }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("0 9 * * 1-5")).toHaveClass("font-mono");
    expect(screen.getByText("Tidy the lead")).toBeInTheDocument();
    // Its own name on top, the kind of step it is under it.
    expect(screen.getByText("Map")).toBeInTheDocument();
  });

  it("falls back to the step's group, keeping its description for a hover", () => {
    seed([
      instance("m", "data.map"),
      instance("f", "control.foreach"),
      instance("e", "error.handle"),
      // No URL, no condition, a step the switch does not know: nothing to say.
      instance("h", "http.request"),
      instance("i", "logic.if"),
      instance("r", "error.raise", { config: { code: "" } }),
      instance("u", "unknown.kind"),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("Data").getAttribute("title")).toBe("Maps fields");
    expect(screen.getByText("Stops at the first failed item")).toBeTruthy();
    expect(screen.getByText("Default branch only")).toBeTruthy();
  });

  it("goes by the name the builder gave, and marks a note, pinned data and a step that is off", () => {
    seed([
      instance("i", "logic.if", { config: { condition: "value.ok" } }),
      instance("m", "data.map", {
        label: "Tidy the lead",
        notes: "For the EU team",
        disabled: true,
        pinned_output: { values: {} },
      }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    expect(screen.getByText("Tidy the lead")).toBeInTheDocument();
    expect(screen.getByTitle("For the EU team")).toHaveAttribute("aria-label", "Has a note");
    expect(screen.getByLabelText(/Switched off/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Has pinned data/)).toBeInTheDocument();
  });

  it("shows a policy and the error port it gives the step", () => {
    seed([
      instance("m", "data.map", {
        policy: { timeout_seconds: 30, retry: { max_attempts: 3 }, on_error: "route" },
      }),
    ]);
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("30s limit")).toBeTruthy();
    expect(screen.getByText("3 tries")).toBeTruthy();
    expect(screen.getByText("Handles errors")).toBeTruthy();
    expect(container.querySelector('[data-port-variant="error"]')).not.toBeNull();
  });

  it("starts a connection without selecting the step it starts from", () => {
    seed([instance("a", "data.map"), instance("b", "data.map")]);
    // xyflow keeps a node hidden until it is measured, which jsdom never does, so
    // the buttons are found by label rather than by role.
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const button = (label: string) =>
      container.querySelector(`button[aria-label="${label}"]`) as HTMLElement;
    fireEvent.click(button("Start a connection from Map port out"));
    expect(store.getState().selection.nodeIds).toEqual([]);
    fireEvent.click(button("Complete the connection to Map port in"));
    expect(store.getState().graph?.edges).toHaveLength(1);
  });

  it("opens a loop body, counting its steps, without selecting the loop", () => {
    seed([instance("f", "control.foreach"), instance("m", "data.map")], {
      edges: [
        {
          id: "e",
          source_node_id: "f",
          source_port: "body",
          target_node_id: "m",
          target_port: "in",
        },
      ],
      scopes: [
        {
          scope_node_id: "f",
          body_node_ids: ["m"],
          entry_port: "body",
          exit_node_id: "f",
          exit_port: "done",
        },
      ],
    });
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("1 step")).toBeTruthy();
    fireEvent.click(
      container.querySelector('button[aria-label="Open the body of Loop"]') as HTMLElement,
    );
    expect(store.getState().scopePath).toEqual(["f"]);
    expect(store.getState().selection.nodeIds).toEqual([]);
  });
});

describe("a node card's +", () => {
  it("adds the chosen step after that output, wired to it, and selects it", async () => {
    seed([instance("i", "logic.if")]);
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    // xyflow keeps an unmeasured node out of the accessibility tree in jsdom.
    await userEvent.click(
      container.querySelector('button[aria-label="Add a step after If (false)"]') as HTMLElement,
    );
    // Map is the only step of its group, so the picker offers it at the top.
    await userEvent.click(await screen.findByText("Map"));

    const graph = store.getState().graph;
    expect(graph?.nodes.map((node) => node.definition_id)).toEqual(["logic.if", "data.map"]);
    expect(graph?.edges).toEqual([
      expect.objectContaining({ source_node_id: "i", source_port: "false" }),
    ]);
    expect(store.getState().selection.nodeIds).toEqual([graph?.nodes[1]?.id]);
  });

  it("sits beside a single output too, and is not offered on a read-only canvas", () => {
    seed([instance("m", "data.map")]);
    const first = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(
      first.container.querySelector('button[aria-label="Add a step after Map (out)"]'),
    ).toBeTruthy();
    first.unmount();

    const readOnly = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />);
    expect(readOnly.container.querySelector('button[aria-label^="Add a step after"]')).toBeNull();
  });
});

describe("a node card on a run's canvas", () => {
  it("says what the run did with it, and fades what the run never reached", () => {
    seed([instance("a", "data.map"), instance("b", "data.map"), instance("c", "data.map")]);
    const summaries = summarizeNodeRuns([
      {
        id: "1",
        node_instance_id: "a",
        scope_path: [],
        status: "failed",
        waiting_reason: null,
        attempts: 2,
        cost: 0,
        error: { code: "BAD", message: "It broke" },
        output: null,
        started_at: null,
        ended_at: null,
      },
      {
        id: "2",
        node_instance_id: "b",
        scope_path: [{ loop_node_id: "l", index: 0 }],
        status: "succeeded",
        waiting_reason: null,
        attempts: 1,
        cost: 0,
        error: null,
        output: null,
        started_at: null,
        ended_at: null,
      },
      {
        id: "3",
        node_instance_id: "b",
        scope_path: [{ loop_node_id: "l", index: 1 }],
        status: "succeeded",
        waiting_reason: null,
        attempts: 1,
        cost: 0,
        error: null,
        output: null,
        started_at: null,
        ended_at: null,
      },
    ]);
    const { container } = render(
      <NodeRunOverlayProvider value={{ summaries, live: false, watched: false }}>
        <WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />
      </NodeRunOverlayProvider>,
    );
    expect(screen.getByText("Failed")).toBeTruthy();
    // The step's own error, under its card.
    expect(screen.getByRole("alert")).toHaveTextContent("BADIt broke");
    expect(screen.getByText("2 tries")).toBeTruthy();
    expect(screen.getByText("2/2 iterations")).toBeTruthy();
    expect(container.querySelector('[data-node-id="c"]')?.className).toContain("opacity-50");
  });
});

describe("a node card's retry policy on a run's canvas", () => {
  const retrying = instance("a", "http.request", {
    policy: { retry: { max_attempts: 3 }, on_error: "fail_run" },
  });
  const row = (attempts: number): WorkflowNodeRunRead => ({
    id: "1",
    node_instance_id: "a",
    scope_path: [],
    status: "failed",
    waiting_reason: null,
    attempts,
    cost: 0,
    error: { code: "URL_REFUSED", message: "Refused" },
    output: null,
    started_at: null,
    ended_at: null,
  });
  const draw = (attempts: number) => {
    seed([retrying]);
    render(
      <NodeRunOverlayProvider
        value={{ summaries: summarizeNodeRuns([row(attempts)]), live: false, watched: false }}
      >
        <WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />
      </NodeRunOverlayProvider>,
    );
  };

  it("says the tries that happened once, not the policy's ceiling beside them", () => {
    draw(3);
    expect(screen.getAllByText("3 tries")).toHaveLength(1);
  });

  it("does not read as three tries when a refusal ended it after one", () => {
    draw(1);
    expect(screen.queryByText("3 tries")).toBeNull();
  });
});

describe("a node card in a run being watched", () => {
  const step = (
    status: WorkflowNodeRunRead["status"],
    extra: Partial<WorkflowNodeRunRead> = {},
  ): WorkflowNodeRunRead => ({
    id: status,
    node_instance_id: "a",
    scope_path: [],
    status,
    waiting_reason: null,
    attempts: 1,
    cost: 0,
    error: null,
    output: null,
    started_at: null,
    ended_at: null,
    ...extra,
  });
  const draw = (rows: WorkflowNodeRunRead[], live: boolean, watched: boolean) => {
    seed([instance("a", "data.map"), instance("b", "data.map")]);
    const { container } = render(
      <NodeRunOverlayProvider value={{ summaries: summarizeNodeRuns(rows), live, watched }}>
        <WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />
      </NodeRunOverlayProvider>,
    );
    const card = (id: string) => container.querySelector(`[data-node-id="${id}"]`)?.className ?? "";
    const pill = (id: string) => container.querySelector(`[data-node-id="${id}"] [data-run-state]`);
    return { card, pill };
  };

  it("glows on the step running and waits dashed on the next, while watched", () => {
    const { card, pill } = draw([step("running")], true, true);
    expect(card("a")).toContain("run-breathe");
    expect(pill("a")).toHaveAttribute("data-run-state", "running");
    expect(card("b")).toContain("border-dashed");
    expect(pill("b")).toHaveTextContent("Pending");
  });

  it("does not glow on a running step of a run it is not watching", () => {
    const { card, pill } = draw([step("running")], false, false);
    expect(pill("a")).toHaveAttribute("data-run-state", "running");
    expect(card("a")).not.toContain("run-breathe");
  });

  it("shows the step after a finished one as starting, glowing, before the engine picks it up", () => {
    const { card, pill } = draw(
      [step("succeeded"), { ...step("pending"), id: "b", node_instance_id: "b" }],
      true,
      true,
    );
    expect(pill("b")).toHaveTextContent("Starting");
    expect(card("b")).toContain("run-breathe");
    expect(card("b")).not.toContain("border-dashed");
  });

  it("shakes a step that fails while watched, and stays still on a run opened after", () => {
    const failed = step("failed", { error: { code: "MODEL_RATE_LIMITED", message: "429" } });
    expect(draw([failed], false, true).card("a")).toContain("run-crash");
    cleanup();
    store.getState().teardown();
    expect(draw([failed], false, false).card("a")).not.toContain("run-crash");
  });

  it("draws a step needing attention as a failure, with its error under it", () => {
    const stuck = step("needs_attention", { error: { code: "UNCERTAIN", message: "Unsure" } });
    const { card, pill } = draw([stuck], false, true);
    expect(card("a")).toContain("border-destructive");
    expect(pill("a")).toHaveTextContent("Needs attention");
    expect(screen.getByRole("alert")).toHaveTextContent("UNCERTAINUnsure");
  });

  it("says how long a step took once done", () => {
    const done = step("succeeded", {
      started_at: "2026-10-19T10:00:00Z",
      ended_at: "2026-10-19T10:00:01.400Z",
    });
    expect(draw([done], false, false).pill("a")).toHaveTextContent("1.4 s");
  });
});
