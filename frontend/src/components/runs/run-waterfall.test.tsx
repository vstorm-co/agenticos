import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { RunWaterfall } from "./run-waterfall";
import type { ManifestRequest } from "@/types/runs";

/**
 * Where a slow run's time actually went.
 *
 * A run is one row with one duration, and forty seconds is either one slow
 * request or nine quick ones with tool calls between them - opposite problems
 * the run row cannot tell apart. The bars are scaled against each other rather
 * than against the run's wall clock, because the gaps between requests are tool
 * executions and a bar including them would blame the model for a slow database.
 */

function request(overrides: Partial<ManifestRequest> = {}): ManifestRequest {
  return {
    index: 0,
    started_at: "2026-08-19T09:00:00Z",
    duration_ms: 400,
    model: "claude-sonnet-4-5",
    message_count: 3,
    input_tokens: 1200,
    output_tokens: 90,
    cache_read_tokens: 0,
    tool_calls: [],
    finish_reason: "stop",
    failed: null,
    ...overrides,
  };
}

function renderWaterfall(requests: ManifestRequest[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunWaterfall requests={requests} />
    </NextIntlClientProvider>,
  );
}

describe("the requests a run made", () => {
  it("scales each bar against the slowest request, not the run", () => {
    const { container } = renderWaterfall([
      request({ index: 0, duration_ms: 200 }),
      request({ index: 1, duration_ms: 800 }),
    ]);

    const widths = [...container.querySelectorAll<HTMLElement>("[style*='width']")].map(
      (bar) => bar.style.width,
    );
    expect(widths).toEqual(["25%", "100%"]);
  });

  it("keeps a near-instant request visible rather than infinitely thin", () => {
    const { container } = renderWaterfall([
      request({ index: 0, duration_ms: 0 }),
      request({ index: 1, duration_ms: 5000 }),
    ]);

    expect(container.querySelector<HTMLElement>("[style*='width']")?.style.width).toBe("4%");
  });

  it("names what the model asked to call next", () => {
    renderWaterfall([request({ tool_calls: ["search_knowledge", "create_chart"] })]);

    expect(screen.getByText("search_knowledge, create_chart")).toBeVisible();
  });

  it("marks the request that raised, by class and never by message", () => {
    // The entry an operator is looking for: a run that died on its fourth
    // request and one that died on its first are the same red row otherwise.
    renderWaterfall([request({ index: 0 }), request({ index: 1, failed: "TimeoutError" })]);

    expect(screen.getByText("TimeoutError")).toBeVisible();
  });

  it("says a run made no request rather than drawing an empty list", () => {
    renderWaterfall([]);

    expect(screen.getByText("This run made no model request.")).toBeVisible();
  });
});
