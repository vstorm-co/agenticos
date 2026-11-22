import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { MessagePart, ToolCall, TurnFileSource } from "@/types/chat";
import type { FileAccess } from "@/lib/file-access";
import { TurnParts } from "./turn-parts";
import { MarkdownContent as RealMarkdown } from "./markdown-content.impl";
import type { MarkdownContentProps } from "./markdown-content";

vi.mock("./markdown-content", () => ({
  MarkdownContent: (props: MarkdownContentProps) => <RealMarkdown {...props} />,
}));
vi.mock("./tool-call-card", () => ({ ToolCallCard: () => null }));
vi.mock("./turn-produced-outputs", () => ({
  TurnProducedOutputs: () => null,
  producedCalls: () => [],
}));
vi.mock("@/components/files", () => ({
  FileViewer: ({
    file,
    access,
    onClose,
  }: {
    file: { path: string };
    access: FileAccess;
    onClose: () => void;
  }) => (
    <div role="dialog">
      <span>{file.path}</span>
      <output>{JSON.stringify(access.textKey)}</output>
      <button onClick={onClose}>Close viewer</button>
    </div>
  ),
}));
const call: ToolCall = {
  id: "write",
  name: "write_file",
  status: "completed",
  args: { path: "files-panel-check.txt", content: "Files panel check" },
  result: "Wrote 1 lines to /workspace/files-panel-check.txt",
};
function View({
  content = "[files-panel-check.txt](/workspace/files-panel-check.txt)",
  source = { kind: "conversation", id: "recorded-origin" },
  receipt = call,
}: {
  content?: string;
  source?: TurnFileSource;
  receipt?: ToolCall;
}) {
  const parts: MessagePart[] = [
    { id: "write-part", type: "tool", toolCall: receipt },
    { id: "answer", type: "text", content },
  ];
  return (
    <TurnParts
      parts={parts}
      isStreaming={false}
      isUser={false}
      mcpServers={[]}
      fileSource={source}
    />
  );
}
it("opens a proven produced markdown file in the existing viewer at its recorded turn origin", () => {
  const view = render(<View />);
  const link = screen.getByRole("button", { name: "files-panel-check.txt" });
  expect(screen.queryByRole("link", { name: "files-panel-check.txt" })).toBeNull();
  fireEvent.click(link);
  expect(screen.getByRole("dialog")).toHaveTextContent("files-panel-check.txt");
  expect(screen.getByRole("status")).toHaveTextContent("recorded-origin");
  view.rerender(
    <View content="[files-panel-check.txt](/workspace/files-panel-check.txt) More text." />,
  );
  expect(screen.getByRole("button", { name: "files-panel-check.txt" })).toBe(link);
  fireEvent.click(screen.getByRole("button", { name: "Close viewer" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("leaves unknown, traversal, external and ordinary console links as normal links", () => {
  render(
    <View
      content={[
        "[unknown](/workspace/unknown.txt)",
        "[traversal](/workspace/../files-panel-check.txt)",
        "[other folder](/workspace/other/files-panel-check.txt)",
        "[external](https://example.com/workspace/files-panel-check.txt)",
        "[settings](/settings)",
        "[query](/workspace/files-panel-check.txt?download=true)",
      ].join("\n\n")}
    />,
  );
  expect(screen.getAllByRole("link")).toHaveLength(6);
  expect(screen.getByRole("link", { name: "external" })).toHaveAttribute(
    "href",
    "https://example.com/workspace/files-panel-check.txt",
  );
  expect(screen.getByRole("link", { name: "settings" })).toHaveAttribute("href", "/settings");
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("does not expose an unavailable private desktop origin as a clickable file", () => {
  render(<View source={{ kind: "local", id: "private-origin-not-on-this-device" }} />);
  expect(screen.getByText("files-panel-check.txt")).toBeVisible();
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.queryByRole("button", { name: "files-panel-check.txt" })).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("does not promote a completed failure to an openable file link", () => {
  render(<View receipt={{ ...call, result: "Error: Failed to write file" }} />);
  expect(screen.getByRole("link", { name: "files-panel-check.txt" })).toHaveAttribute(
    "href",
    "/workspace/files-panel-check.txt",
  );
});
it("does not reuse an already opened viewer after the turn origin changes", () => {
  const view = render(<View />);
  fireEvent.click(screen.getByRole("button", { name: "files-panel-check.txt" }));
  view.rerender(<View source={{ kind: "conversation", id: "other-origin" }} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "files-panel-check.txt" }));
  expect(screen.getByRole("status")).toHaveTextContent("other-origin");
});
