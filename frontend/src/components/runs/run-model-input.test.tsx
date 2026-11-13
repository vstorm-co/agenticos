import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";
import messages from "../../../messages/en.json";
import type { ManifestRequest, RunManifest } from "@/types/runs";
import { RunModelInput } from "./run-model-input";

function request(overrides: Partial<ManifestRequest> = {}): ManifestRequest {
  return {
    index: 0,
    started_at: null,
    duration_ms: 100,
    model: "test",
    message_count: 2,
    input_tokens: 1000,
    output_tokens: 200,
    cache_read_tokens: 500,
    cache_write_tokens: 100,
    tool_calls: [],
    finish_reason: "stop",
    failed: null,
    cache_missed_tokens: 0,
    ...overrides,
  };
}
function record(overrides: Partial<RunManifest> = {}): RunManifest {
  return {
    run_id: "run",
    recorded_at: "2026-11-13T12:00:00Z",
    instructions: "Hello {{name}}.",
    system_prompts: ["Keep {{organization.name}} in mind."],
    tools: [],
    settings: {},
    requests: [],
    messages: [],
    truncated: false,
    ...overrides,
  };
}
function show(manifest: RunManifest) {
  return render(
    <NextIntlClientProvider locale="en" timeZone="UTC" messages={messages}>
      <RunModelInput manifest={manifest} />
    </NextIntlClientProvider>,
  );
}
function tab(name: RegExp) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0, ctrlKey: false });
}
const policy = {
  strategy: "local_bm25",
  max_results: 5,
  defer_capabilities: true,
  defer_mcp_servers: true,
  exclude_capabilities: ["sandbox"],
  exclude_mcp_servers: ["trusted"],
  exclude_tools: ["clock"],
};

describe("recorded model input", () => {
  it("shows aggregate usage without counting cache on top of input", () => {
    show(
      record({
        settings: { thinking: true },
        requests: [request(), request({ index: 1, cache_write_tokens: 20 })],
      }),
    );
    expect(screen.getByText("thinking true")).toBeVisible();
    const input = screen.getByText("Input tokens").parentElement;
    expect(input).toHaveTextContent("2,000");
    expect(screen.getByText("Cache write").parentElement).toHaveTextContent("120");
    expect(screen.getByText("Output tokens").parentElement).toHaveTextContent("400");
  });
  it("labels missing cache-write evidence rather than asserting zero", () => {
    show(record({ requests: [request({ cache_write_tokens: null })] }));
    expect(screen.getByText("Cache write").parentElement).toHaveTextContent("Not recorded");
    expect(screen.queryByText("Model settings")).not.toBeInTheDocument();
  });
  it("keeps settings readable even when no request was recorded", () => {
    show(record({ settings: { temperature: 0 } }));
    expect(screen.getByText("temperature 0")).toBeVisible();
    expect(screen.queryByText("Input tokens")).not.toBeInTheDocument();
  });
  it("preserves prompt source boundaries and highlights variables in both views", async () => {
    const { container } = show(record());
    await waitFor(() => expect(container.querySelectorAll("mark")).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(container.querySelector("pre")).toHaveTextContent("Hello {{name}}.");
    expect(container.querySelectorAll("pre span[class]")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Read" }));
    await waitFor(() => expect(container.querySelectorAll("mark")).toHaveLength(2));
  });
  it("offers useful visibility filters and search, including no-match and paging states", () => {
    const tools: RunManifest["tools"] = Array.from({ length: 25 }, (_, index) => ({
      name: `tool_${index}`,
      description:
        index === 0 ? "<summary>Read a record</summary><returns>A result</returns>" : null,
      kind: "function",
      parameters_json_schema: { type: "object" },
      visibility: index === 0 ? "visible" : "deferred",
    }));
    show(
      record({
        tools,
        tool_search: policy,
        requests: [
          request({ tool_counts: { visible: 1, deferred: 24, withheld: 0, via_history: 0 } }),
        ],
      }),
    );
    expect(screen.getByText("Tool Search enabled")).toBeVisible();
    tab(/^Tools/);
    expect(screen.getByText("sandbox, trusted, clock")).toBeInTheDocument();
    expect(screen.queryByText("tool_24")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show more tools" }));
    expect(screen.getByText("tool_24")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Visible" }));
    expect(screen.getByText("1 of 25 tools")).toBeVisible();
    expect(screen.getByText(/Read a record/)).not.toHaveTextContent("<summary>");
    fireEvent.click(screen.getByRole("button", { name: "Deferred" }));
    expect(screen.getByText("24 of 25 tools")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Withheld" }));
    expect(screen.getByText("No tools match your search.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Tool catalog" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search tool names and descriptions…" }), {
      target: { value: "tool_24" },
    });
    expect(screen.getByText("1 of 25 tools")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Search tool names and descriptions…" }), {
      target: { value: "missing" },
    });
    expect(screen.getByText("No tools match your search.")).toBeVisible();
  });
  it("labels legacy visibility honestly and renders each request's retained evidence", () => {
    show(
      record({
        tools: [
          { name: "legacy", description: null, kind: "function", parameters_json_schema: {} },
        ],
        requests: [
          request({
            visible_tool_names: ["clock"],
            tool_counts: { visible: 1, deferred: 2, withheld: 3, via_history: 4 },
          }),
          request({ index: 1, visible_tool_names: null }),
        ],
      }),
    );
    tab(/^Tools/);
    expect(screen.getByText("legacy")).toBeVisible();
    expect(screen.getByText("Not recorded")).toBeVisible();
    tab(/^Requests/);
    expect(screen.getByText("clock", { exact: true })).toBeInTheDocument();
    expect(
      screen.getByText("Visible tool names were not retained in this record."),
    ).toBeInTheDocument();
    expect(screen.getByText("Deferred: 2")).toBeInTheDocument();
  });
  it("does not invent exceptions or tools when none were recorded", () => {
    show(
      record({
        instructions: null,
        system_prompts: [],
        tool_search: {
          ...policy,
          exclude_capabilities: [],
          exclude_mcp_servers: [],
          exclude_tools: [],
        },
      }),
    );
    expect(screen.getByText("No instructions were sent with this run.")).toBeVisible();
    tab(/^Tools/);
    expect(screen.getByText("No always-visible exceptions.")).toBeInTheDocument();
    expect(screen.getByText("The model was given no tools.")).toBeVisible();
  });
});
