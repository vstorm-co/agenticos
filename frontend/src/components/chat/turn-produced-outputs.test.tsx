import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MediaSurfaceContext } from "@/lib/generated-media";
import type { ToolCall } from "@/types";
import { TurnProducedOutputs } from "./turn-produced-outputs";
vi.mock("./tool-results/workspace", () => ({
  WorkspaceFileCard: ({ path }: { path: string }) => <span>{path}</span>,
}));
vi.mock("./tool-results/coding-agent", async () => {
  const original = await vi.importActual<typeof import("./tool-results/coding-agent")>(
    "./tool-results/coding-agent",
  );
  return {
    ...original,
    CodingAgentResult: ({ resultText }: { resultText: string }) => <span>{resultText}</span>,
  };
});

const call = (name: string, result: unknown, extra: Partial<ToolCall> = {}): ToolCall => ({
  id: name,
  name,
  status: "completed",
  args: {},
  result,
  ...extra,
});
it("shows produced media exactly once outside diagnostic steps", () => {
  const view = render(
    <TurnProducedOutputs
      calls={[
        call(
          "generate_image",
          JSON.stringify({
            kind: "generated_image",
            filename: "image.png",
            prompt: "A lighthouse",
          }),
        ),
        call(
          "generate_speech",
          JSON.stringify({
            kind: "generated_speech",
            filename: "voice.mp3",
            text: "Spoken answer",
          }),
        ),
        call(
          "generate_video",
          JSON.stringify({
            kind: "generated_video",
            filename: "clip.mp4",
            prompt: "Moving clouds",
          }),
        ),
        call(
          "computer_save_screenshot",
          JSON.stringify({
            kind: "desktop_screenshot",
            filename: "screen.png",
            caption: "Saved evidence",
          }),
        ),
      ]}
    />,
  );
  expect(screen.getByRole("img", { name: "A lighthouse" })).toHaveAttribute(
    "src",
    "/api/generated/image.png",
  );
  expect(screen.getByRole("img", { name: "Saved evidence" })).toHaveAttribute(
    "src",
    "/api/generated/screen.png",
  );
  expect(view.container.querySelectorAll("audio")).toHaveLength(1);
  expect(view.container.querySelectorAll("video")).toHaveLength(1);
});
it("keeps produced workspace files and coding change reports accessible", () => {
  render(
    <TurnProducedOutputs
      calls={[
        call("write_file", "written", { args: { path: "report.md" } }),
        call("edit_file", "edited", { args: { path: "existing.md" } }),
        call(
          "run_coding_agent",
          JSON.stringify({
            kind: "coding_agent",
            harness: "codex",
            access: "edit",
            outcome: "completed",
            answer: "Review these changes",
          }),
        ),
      ]}
    />,
  );
  expect(screen.getByText("report.md")).toBeVisible();
  expect(screen.getByText("existing.md")).toBeVisible();
  expect(screen.getByText(/Review these changes/)).toBeVisible();
});
it("never promotes failed, pending, malformed or generic external data to a visual output", () => {
  const { container } = render(
    <TurnProducedOutputs
      calls={[
        call("write_file", "failed", { status: "error", args: { path: "missing.md" } }),
        call("generate_image", "waiting", { status: "running" }),
        ...["generate_image", "generate_speech", "generate_video", "computer_save_screenshot"].map(
          (name) => call(name, "not media"),
        ),
        call("write_file", "no path"),
        call("edit_file", null),
        call("run_coding_agent", JSON.stringify({ kind: "coding_agent", steps: "invalid" })),
        call("recall", "profile role"),
        call("generate_image", "not native", { presentation_kind: "generic", tool_id: null }),
      ]}
    />,
  );
  expect(container).toBeEmptyDOMElement();
});
it("retains the immutable file source and the registered identity of renamed writes", () => {
  render(
    <TurnProducedOutputs
      fileSource={{ kind: "conversation", id: "source" }}
      calls={[call("save_report", "ok", { tool_id: "write_file", args: { path: "renamed.md" } })]}
    />,
  );
  expect(screen.getByText("renamed.md")).toBeVisible();
});
it("uses the hosted surface token for media instead of a private console address", () => {
  render(
    <MediaSurfaceContext value={{ kind: "hosted", publicKey: "page" }}>
      <TurnProducedOutputs
        calls={[
          call(
            "computer_save_screenshot",
            JSON.stringify({
              kind: "desktop_screenshot",
              filename: "screen.png",
              caption: "Public evidence",
              token: "scoped",
            }),
          ),
        ]}
      />
    </MediaSurfaceContext>,
  );
  expect(screen.getByRole("img", { name: "Public evidence" })).toHaveAttribute(
    "src",
    "/api/embed/page/generated/screen.png?token=scoped",
  );
});

it("accepts structured media results and keeps an absent output empty", () => {
  render(
    <TurnProducedOutputs
      calls={[
        call("generate_image", {
          kind: "generated_image",
          filename: "structured.png",
          prompt: "Structured image",
        }),
        call("edit_file", undefined),
      ]}
    />,
  );
  expect(screen.getByRole("img", { name: "Structured image" })).toHaveAttribute(
    "src",
    "/api/generated/structured.png",
  );
});

it("keeps repeated writes to one file as a single produced document", () => {
  render(
    <TurnProducedOutputs
      calls={[
        call("write_file", "created", { id: "write", args: { path: "report.md" } }),
        call("edit_file", "edited", { id: "edit", args: { path: "report.md" } }),
      ]}
    />,
  );
  expect(screen.getAllByText("report.md")).toHaveLength(1);
});
