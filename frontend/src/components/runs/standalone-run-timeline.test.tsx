import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ApiError } from "@/lib/api-client";
import { StandaloneRunTimeline } from "./standalone-run-timeline";

const useManifest = vi.fn();
vi.mock("@/hooks", () => ({ useRunManifest: (id: string) => useManifest(id) }));

function draw() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <StandaloneRunTimeline runId="proactive-run" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useManifest.mockReset());

it("loads the selected run before declaring its transcript absent", () => {
  useManifest.mockReturnValue({ isLoading: true });
  draw();
  expect(screen.getByRole("status")).toBeVisible();
  expect(useManifest).toHaveBeenCalledWith("proactive-run");
});

it("shows a read error instead of claiming nothing was recorded", () => {
  useManifest.mockReturnValue({ error: new Error("offline") });
  draw();
  expect(screen.getByText(messages.pages.runs.transcriptCouldNotBeRead)).toBeVisible();
});

it.each([undefined, new ApiError(404, "Nothing recorded")])(
  "keeps old runs readable (%s)",
  (error) => {
    useManifest.mockReturnValue({ error });
    draw();
    expect(screen.getByText("No transcript recorded")).toBeVisible();
  },
);

it.each([false, true])(
  "distinguishes a trimmed trace from an old empty record (%s)",
  (truncated) => {
    useManifest.mockReturnValue({ manifest: { transcript: [], truncated } });
    draw();
    expect(screen.getByText("No transcript recorded")).toBeVisible();
    if (truncated) expect(screen.getByText(messages.pages.runs.recordWasTrimmed)).toBeVisible();
  },
);

it.each([false, true])(
  "renders the real request, tool returns and final structured answer (%s)",
  (truncated) => {
    useManifest.mockReturnValue({
      manifest: {
        truncated,
        transcript: [
          { kind: "request", parts: [{ part_kind: "user-prompt", content: "Read my week" }] },
          { kind: "request", parts: [{ part_kind: "tool-return", content: "PR #12 waiting" }] },
          {
            kind: "response",
            parts: [{ part_kind: "tool-call", args: { summary: "Review PR #12" } }],
          },
        ],
      },
    });
    draw();
    expect(screen.getAllByText("Model request")).toHaveLength(2);
    expect(screen.getByText("Model response")).toBeVisible();
    expect(screen.getByText(/Read my week/)).toBeVisible();
    expect(screen.getByText(/PR #12 waiting/)).toBeVisible();
    expect(screen.getByText(/Review PR #12/)).toBeVisible();
    expect(screen.getAllByRole("button")).toHaveLength(3);
  },
);
