import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RunTimeline } from "./run-timeline";
import type { RunTranscript, RunTranscriptMessage } from "@/types/runs";

/**
 * The trace view's claims: the whole thread is asked for and the focused run's
 * turns are the marked ones; a tool call reads raw - name, status, input JSON,
 * recorded output - not through the chat's renderers; and a run with no
 * conversation says so rather than drawing an empty page.
 */

const useRunTranscriptMock = vi.fn();
vi.mock("@/hooks", () => ({
  useRunTranscript: (runId: string, scope?: string) => useRunTranscriptMock(runId, scope),
}));

function turn(overrides: Partial<RunTranscriptMessage> = {}): RunTranscriptMessage {
  return {
    id: `m-${Math.random().toString(36).slice(2, 8)}`,
    role: "assistant",
    content: "Done.",
    created_at: "2026-08-14T09:00:00Z",
    run_id: "run-1",
    ...overrides,
  };
}

function serve(transcript: Partial<RunTranscript>) {
  useRunTranscriptMock.mockReturnValue({
    transcript: { run_id: "run-1", conversation_id: "conv-1", items: [], total: 0, ...transcript },
    isLoading: false,
    error: null,
  });
}

function renderTimeline(runId = "run-1") {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunTimeline runId={runId} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useRunTranscriptMock.mockReset());

describe("the thread and the run inside it", () => {
  it("asks for the whole conversation and marks the focused run's turns", () => {
    serve({
      items: [
        turn({ id: "m-ctx", role: "user", content: "earlier question", run_id: "run-0" }),
        turn({ id: "m-own", role: "user", content: "the question", run_id: "run-1" }),
      ],
    });

    renderTimeline();

    expect(useRunTranscriptMock).toHaveBeenCalledWith("run-1", "conversation");
    // Context is on screen but only the run's own turns carry the marker.
    expect(screen.getByText("earlier question")).toBeVisible();
    expect(screen.getAllByText("This run")).toHaveLength(1);
    expect(screen.getByText("the question").closest("li")?.textContent).toContain("This run");
  });

  it("scrolls the reader to the run's first turn, not the top of the thread", () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    serve({
      items: [
        turn({ id: "m-ctx", run_id: "run-0" }),
        turn({ id: "m-own", run_id: "run-1" }),
        turn({ id: "m-own-2", run_id: "run-1" }),
      ],
    });

    renderTimeline();

    // Once - the first own turn is the landing, the second is below it.
    expect(scrolled).toHaveBeenCalledTimes(1);
  });
});

describe("a tool call, raw", () => {
  it("shows the wire: name, stored status, input JSON and recorded output", async () => {
    serve({
      items: [
        turn({
          id: "m-1",
          parts: [{ type: "tool", tool_call_id: "call-1" }],
          tool_calls: [
            {
              tool_call_id: "call-1",
              tool_name: "web_search",
              args: { query: "pgvector" },
              result: "3 results",
              status: "completed",
            },
          ],
        }),
      ],
    });

    renderTimeline();

    const step = screen.getByText("web_search").closest("details") as HTMLElement;
    expect(within(step).getByText("completed")).toBeVisible();

    await userEvent.click(within(step).getByText("web_search"));

    expect(within(step).getByText(/"query": "pgvector"/)).toBeVisible();
    expect(within(step).getByText("3 results")).toBeVisible();
  });

  it("keeps the stored order: reasoning, tools and text interleaved as written", () => {
    serve({
      items: [
        turn({
          id: "m-1",
          content: "unused when parts are stored",
          thinking: "unused too",
          parts: [
            { type: "text", text: "Let me check." },
            { type: "tool", tool_call_id: "call-1" },
            { type: "text", text: "All done." },
          ],
          tool_calls: [
            {
              tool_call_id: "call-1",
              tool_name: "list_files",
              args: {},
              result: null,
              status: "completed",
            },
          ],
        }),
      ],
    });

    renderTimeline();

    const row = screen.getByText("Let me check.").closest("li") as HTMLElement;
    const order = row.textContent ?? "";
    expect(order.indexOf("Let me check.")).toBeLessThan(order.indexOf("list_files"));
    expect(order.indexOf("list_files")).toBeLessThan(order.indexOf("All done."));
  });

  it("folds reasoning behind a disclosure rather than printing the trace whole", () => {
    serve({
      items: [turn({ id: "m-1", thinking: "chain of thought", content: "Answer." })],
    });

    renderTimeline();

    expect(screen.getByText("Reasoning")).toBeVisible();
    expect(screen.getByText("chain of thought").closest("details")).not.toBeNull();
  });
});

describe("what people said about it", () => {
  it("puts the verdict and the words on the turn they judged", () => {
    serve({
      items: [
        turn({
          id: "m-1",
          rating_count: { likes: 0, dislikes: 2 },
          rating_comment: "wrong currency",
        }),
      ],
    });

    renderTimeline();

    expect(screen.getByText("Rated down 2 times")).toBeVisible();
    expect(screen.getByText("wrong currency")).toBeVisible();
  });
});

describe("a run outside any conversation", () => {
  it("says no transcript was recorded rather than drawing an empty page", () => {
    serve({ conversation_id: null });

    renderTimeline();

    expect(screen.getByText("No transcript recorded")).toBeVisible();
  });

  it("says the read failed rather than that nothing happened", () => {
    useRunTranscriptMock.mockReturnValue({
      transcript: undefined,
      isLoading: false,
      error: new Error("502"),
    });

    renderTimeline();

    expect(screen.getByText("The transcript could not be read")).toBeVisible();
  });
});
