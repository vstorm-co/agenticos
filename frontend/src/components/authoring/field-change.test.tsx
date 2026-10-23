import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useTranslations } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { hunk } from "@/test-utils/authoring";
import type { Hunk } from "@/types/authoring";
import { editable, fieldLabel, parsed } from "./field-change";
import { SuggestionCard } from "./suggestion-card";

function field(overrides: Partial<Hunk>): Hunk {
  return hunk({ kind: "spec_field", op: "set", names: {}, ...overrides });
}

function Labels({ hunks }: { hunks: Hunk[] }) {
  const t = useTranslations("authoring.field");
  return (
    <ul>
      {hunks.map((item) => (
        <li key={`${item.path}-${item.op}`}>{fieldLabel(item, t)}</li>
      ))}
    </ul>
  );
}

function card(item: Hunk, onDecide = vi.fn()) {
  render(<SuggestionCard hunk={item} canEdit busy={false} onDecide={onDecide} />);
  return onDecide;
}

describe("a field change", () => {
  it("names the field it changes in words, and what it adds or removes by name", () => {
    const names = { "kb-1": "Policies", "conn-1": "CRM", artifacts: "Apps", "ctx-1": "Tone" };
    render(
      <Labels
        hunks={[
          field({ path: "description" }),
          field({ path: "model_profile_id" }),
          field({ path: "max_steps" }),
          field({ path: "model_settings/temperature" }),
          field({ path: "capabilities", op: "add", new_value: { id: "artifacts" }, names }),
          field({ path: "capabilities", op: "remove", base_value: { id: "charts" } }),
          field({ path: "collection_ids", op: "add", new_value: "kb-1", names }),
          field({ path: "collection_ids", op: "remove", base_value: "kb-2" }),
          field({ path: "context_ids", op: "add", new_value: "ctx-1", names }),
          field({ path: "context_ids", op: "remove", base_value: "ctx-2" }),
          field({ path: "mcp_servers/conn-1/allowed_tools", names }),
          field({ path: "mcp_servers/personal:notion/allowed_tools" }),
          field({ path: "capabilities/subagents/inline/triage/description" }),
          field({ path: "capabilities/knowledge/config" }),
          field({ path: "capabilities/sandbox/approval" }),
          field({ path: "capabilities/sandbox/tool_approval/execute" }),
          field({ path: null }),
        ]}
      />,
    );
    for (const label of [
      "Description",
      "Model",
      "Step limit",
      "Temperature",
      "Add capability Apps",
      "Remove capability charts",
      "Add knowledge base Policies",
      "Remove knowledge base kb-2",
      "Add context file Tone",
      "Remove context file ctx-2",
      "MCP tools of CRM",
      "MCP tools of personal:notion",
      "Description of specialist triage",
      "Settings of knowledge",
      "Approval for sandbox",
      "Approval for tool execute",
      "Approval for tool",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("lets a single setting or a text be edited, as the value the field holds", () => {
    expect(editable("model_settings/temperature")).toBe("number");
    expect(editable("max_steps")).toBe("number");
    expect(editable("model_settings/parallel_tool_calls")).toBe("boolean");
    expect(editable("capabilities/subagents/inline/x/description")).toBe("text");
    expect(editable("collection_ids")).toBeNull();
    expect(editable(null)).toBeNull();
    expect(parsed("max_steps", "12")).toBe(12);
    expect(parsed("max_steps", " ")).toBeNull();
    expect(parsed("model_settings/parallel_tool_calls", "true")).toBe(true);
    expect(parsed("description", "Refunds")).toBe("Refunds");
  });

  it("shows a value before and after, named, and accepts the person's own number", async () => {
    const onDecide = card(
      field({ path: "model_settings/temperature", base_value: null, new_value: 0.2 }),
    );
    expect(screen.getByText("Not set")).toBeInTheDocument();
    expect(screen.getByText("0.2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("spinbutton", { name: "Your value" });
    await userEvent.clear(box);
    await userEvent.type(box, "0.4");
    await userEvent.click(screen.getByRole("button", { name: "Save and accept" }));

    expect(onDecide).toHaveBeenCalledWith({ action: "accept", value: 0.4 });
  });

  it("will not accept an emptied number, which would read as no edit at all", async () => {
    card(field({ path: "max_steps", base_value: 10, new_value: 20 }));
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Your value" }));
    expect(screen.getByRole("button", { name: "Save and accept" })).toBeDisabled();
  });

  it("offers a yes or no for a switch, and a box for a text", async () => {
    const onDecide = card(
      field({ path: "model_settings/parallel_tool_calls", base_value: true, new_value: false }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Your value" }), "true");
    await userEvent.click(screen.getByRole("button", { name: "Save and accept" }));
    expect(onDecide).toHaveBeenCalledWith({ action: "accept", value: true });
  });

  it("edits a description in a box", async () => {
    const onDecide = card(field({ path: "description", base_value: "Old", new_value: "New" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Your value" });
    await userEvent.clear(box);
    await userEvent.type(box, "Mine");
    await userEvent.click(screen.getByRole("button", { name: "Save and accept" }));
    expect(onDecide).toHaveBeenCalledWith({ action: "accept", value: "Mine" });
  });

  it("names what it adds, says what it reaches that writes, and offers no edit", () => {
    card(
      field({
        path: "capabilities",
        op: "add",
        new_value: { id: "artifacts", config: {} },
        names: { artifacts: "Apps" },
        effect: { writes: ["publish_artifact"] },
        expected_effect: "Answers can be published",
      }),
    );
    expect(screen.getByText(/Adds\s+Apps/)).toBeInTheDocument();
    expect(screen.getByText(/Reaches tools that change things: publish_artifact/)).toBeVisible();
    expect(screen.getByText("Expected: Answers can be published")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("shows what it removes, and a configuration as it reads", () => {
    card(field({ path: "collection_ids", op: "remove", base_value: "kb-9" }));
    expect(screen.getByText(/Removes\s+kb-9/)).toBeInTheDocument();
  });

  it("shows a changed configuration in full", () => {
    card(
      field({
        path: "capabilities/knowledge/config",
        base_value: { default_top_k: 5 },
        new_value: { default_top_k: 8 },
        status: "accepted",
        accepted_value: { default_top_k: 9 },
      }),
    );
    expect(screen.getByText(/"default_top_k": 9/)).toBeInTheDocument();
  });

  it("says what a change of model costs, how roughly, and why accepting it waits", () => {
    card(
      field({
        path: "model_profile_id",
        base_value: "m-1",
        new_value: "m-2",
        names: { "m-1": "GPT-4o", "m-2": "GPT-4o mini" },
        effect: { runs: 3, rough: true, cost_per_run_before: "0.01", cost_per_run_after: "0.002" },
        blocked: "check_first",
      }),
    );
    expect(screen.getByText("GPT-4o")).toBeInTheDocument();
    expect(screen.getByText(/costs about \$0.01 now and \$0.002/)).toBeVisible();
    expect(screen.getByText(/A rough estimate, from 3 runs/)).toBeVisible();
    expect(screen.getByRole("note")).toHaveTextContent("Run Check with evals");
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  });

  it("says when a change of model cannot be priced", () => {
    card(
      field({
        path: "model_profile_id",
        base_value: "m-1",
        new_value: "m-2",
        effect: { runs: 6, rough: false, cost_per_run_before: null, cost_per_run_after: "1" },
      }),
    );
    expect(
      screen.getByText("What a run would cost cannot be priced for one of these models."),
    ).toBeVisible();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("marks what it adds access to, by name, and that tools that write ask for approval", () => {
    card(
      field({
        path: "capabilities",
        op: "add",
        new_value: { id: "artifacts" },
        names: { artifacts: "Apps", "kb-1": "Orders" },
        effect: {
          writes: ["publish_artifact"],
          adds: [
            { kind: "capability", id: "artifacts", tools: ["publish_artifact"] },
            { kind: "collection", id: "kb-1", tools: [] },
            { kind: "context", id: "ctx-9", tools: [] },
          ],
        },
      }),
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "Adds access: capability “Apps”, its tool that writes asking for approval, knowledge base “Orders”, and context file “ctx-9”",
    );
    expect(screen.queryByText(/Undo puts the tools back/)).toBeNull();
  });

  it("names widened MCP tools and that Undo keeps them asking", () => {
    card(
      field({
        path: "mcp_servers/conn-1/allowed_tools",
        base_value: ["find"],
        new_value: ["find", "lookup_order", "refund"],
        names: { "conn-1": "Shop" },
        effect: {
          adds: [
            { kind: "mcp_tools", id: "conn-1", tools: ["lookup_order", "refund"] },
            { kind: "mcp_tools", id: "personal:notion", tools: [] },
          ],
        },
      }),
    );
    expect(
      screen.getByText(
        "Adds access: tools lookup_order and refund of Shop, asking for approval where they write and every tool of personal:notion, asking for approval where they write",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Where the server asked for nothing, accepting makes every tool of it that writes ask for approval - not only the added ones. Undo puts the tools back and keeps them asking.",
      ),
    ).toBeVisible();
  });

  it("holds a change of model back while its check measured something else", () => {
    card(
      field({
        path: "model_profile_id",
        base_value: "m-1",
        new_value: "m-2",
        blocked: "check_outdated",
      }),
    );
    expect(screen.getByRole("note")).toHaveTextContent("The check is out of date");
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  });
});
