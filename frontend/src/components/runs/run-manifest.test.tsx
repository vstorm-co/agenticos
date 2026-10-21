import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RunManifest } from "./run-manifest";
import { ApiError } from "@/lib/api-client";
import type { RunManifest as RunManifestRecord } from "@/types/runs";

/**
 * What the model was given, which nothing else in the product shows.
 *
 * The prompt here is not the spec's text: it is the spec's plus the platform's
 * plus whatever a binding appended plus the bound skills', recorded from the
 * wire. Same for the tools - the registry plus the organization's MCP servers
 * minus whatever tool search hid. So the panel's claim is "this is what was
 * sent", and the tests below are about the two ways that claim can be broken:
 * by drawing a record that was trimmed as though it were complete, and by
 * drawing a run that recorded nothing as a run that was given nothing.
 */

const useRunManifestMock = vi.fn();
vi.mock("@/hooks", () => ({
  useRunManifest: (runId: string) => useRunManifestMock(runId),
}));

function record(overrides: Partial<RunManifestRecord> = {}): RunManifestRecord {
  return {
    run_id: "run-1",
    recorded_at: "2026-08-19T09:00:00Z",
    instructions: "You are a clerk.",
    system_prompts: [],
    tools: [],
    settings: {},
    requests: [],
    messages: [],
    truncated: false,
    ...overrides,
  };
}

function serve(answer: { manifest?: RunManifestRecord; isLoading?: boolean; error?: unknown }) {
  useRunManifestMock.mockReturnValue({
    manifest: answer.manifest,
    isLoading: answer.isLoading ?? false,
    error: answer.error ?? null,
  });
}

function renderManifest() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunManifest runId="run-1" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useRunManifestMock.mockReset());

describe("what the model was told", () => {
  it("lists each reviewer's correction, and who sent it, after which request (#2106)", () => {
    serve({
      manifest: record({
        reviews: [{ reviewer: "sources", after_request: 6, steer: "Cite a source for 40%." }],
      }),
    });
    renderManifest();

    expect(screen.getByText("1 reviewer correction")).toBeInTheDocument();
    expect(screen.getByText("sources, after request 6")).toBeInTheDocument();
    expect(screen.getByText("Cite a source for 40%.")).toBeInTheDocument();
  });

  it("shows no reviewer section for a run nobody reviewed", () => {
    serve({ manifest: record() });
    renderManifest();
    expect(screen.queryByText(/reviewer correction/)).toBeNull();
  });

  it("shows each script code mode ran, and every call it made (#2107)", () => {
    serve({
      manifest: record({
        code_runs: [
          {
            tool_call_id: "c1",
            code: "await update_record(n=1)",
            calls: [
              { tool: "update_record", args: '{"n": 1}', status: "returned" },
              { tool: "update_record", args: '{"n": 2}', status: "failed" },
            ],
          },
        ],
      }),
    });
    renderManifest();

    expect(screen.getByText("1 script")).toBeInTheDocument();
    expect(screen.getByText("await update_record(n=1)")).toBeInTheDocument();
    expect(screen.getByText("It made 2 tool calls")).toBeInTheDocument();
    expect(screen.getByText('{"n": 2}')).toBeInTheDocument();
  });

  it("counts the calls a long script made past the listed ones", () => {
    serve({
      manifest: record({
        code_runs: [
          {
            tool_call_id: "c1",
            code: "loop()",
            calls: [{ tool: "update_record", args: '{"n": 1}', status: "returned" }],
            omitted_calls: 250,
          },
        ],
      }),
    });
    renderManifest();

    expect(screen.getByText("It made 251 tool calls")).toBeInTheDocument();
    expect(screen.getByText("and 250 more calls, not listed")).toBeInTheDocument();
  });

  it("shows the prompt as it was sent, and the system parts beside it", () => {
    serve({
      manifest: record({
        instructions: "You are a clerk. Be brief.",
        system_prompts: ["Answer in English."],
      }),
    });

    renderManifest();

    expect(screen.getByText("You are a clerk. Be brief.")).toBeVisible();
    expect(screen.getByText("Answer in English.")).toBeVisible();
  });

  it("leads each tool with the sentence the model decides on", () => {
    // An agent that never calls a tool it has is usually an agent whose tool
    // describes itself badly, and this is the only surface showing that sentence.
    serve({
      manifest: record({
        tools: [
          {
            name: "check_stock",
            description: "Look up how many of one item are in the warehouse.",
            parameters_json_schema: { type: "object", properties: { sku: { type: "string" } } },
            kind: "function",
          },
        ],
      }),
    });

    renderManifest();

    expect(screen.getByText("1 tool")).toBeVisible();
    expect(screen.getByText("Look up how many of one item are in the warehouse.")).toBeVisible();
    expect(screen.getByText(/"sku"/)).toBeInTheDocument();
  });

  it("says the model was given no tools rather than showing an empty list", () => {
    serve({ manifest: record({ tools: [] }) });

    renderManifest();

    expect(screen.getByText("The model was given no tools.")).toBeVisible();
  });

  it("shows the settings that were sent", () => {
    serve({ manifest: record({ settings: { temperature: 0.2 } }) });

    renderManifest();

    expect(screen.getByText("temperature 0.2")).toBeVisible();
  });

  it("draws no settings section when none were sent", () => {
    serve({ manifest: record({ settings: {} }) });

    renderManifest();

    expect(screen.queryByText("Model settings")).toBeNull();
  });

  it("says a run sent no instructions rather than leaving the panel blank", () => {
    serve({ manifest: record({ instructions: null }) });

    renderManifest();

    expect(screen.getByText("No instructions were sent with this run.")).toBeVisible();
  });
});

describe("a record that could not be kept whole", () => {
  it("says it was trimmed", () => {
    // A trimmed document read as a complete one says the agent was given no
    // schemas, which is a claim about the agent rather than about the record.
    serve({ manifest: record({ truncated: true }) });

    renderManifest();

    expect(screen.getByText(/trimmed to fit its size limit/)).toBeVisible();
  });

  it("offers the last request's context, folded", () => {
    serve({ manifest: record({ messages: [{ kind: "request", parts: [] }] }) });

    renderManifest();

    expect(screen.getByText("1 message")).toBeVisible();
  });
});

describe("a run with nothing recorded", () => {
  it("says which nothing it is, not that the request failed", () => {
    serve({ error: new ApiError(404, "nothing recorded", undefined) });

    renderManifest();

    expect(screen.getByText("Nothing was recorded for this run")).toBeVisible();
  });

  it("says the read failed when it did", () => {
    serve({ error: new Error("502") });

    renderManifest();

    expect(screen.getByText("What went in could not be read")).toBeVisible();
  });

  it("waits rather than claiming either while the answer is in flight", () => {
    serve({ isLoading: true });

    renderManifest();

    expect(screen.queryByText("Nothing was recorded for this run")).toBeNull();
  });
});
