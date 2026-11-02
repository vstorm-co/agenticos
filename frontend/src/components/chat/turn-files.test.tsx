import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { FileSource } from "@/lib/workspace-files";
import type { ChatMessage } from "@/types/chat";
import { useWorkOnStore } from "@/stores/work-on-store";
import { TurnFiles } from "./turn-files";

const env = vi.hoisted(() => ({ source: null as FileSource | null, access: vi.fn() }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => ({ platform: "macos" }) }));
vi.mock("@/lib/workspace-files", () => ({
  workspaceFileAccess: (...args: unknown[]) => env.access(...args),
}));
vi.mock("@/components/files", () => ({
  FileIcon: () => null,
  FileViewer: ({
    file,
    onClose,
    navigation,
  }: {
    file: { path: string };
    onClose: () => void;
    navigation: { onSelect: (index: number) => void };
  }) => (
    <div role="dialog">
      <span>{file.path}</span>
      <button onClick={onClose}>Close</button>
      <button onClick={() => navigation.onSelect(1)}>Next</button>
      <button onClick={() => navigation.onSelect(99)}>Outside</button>
    </div>
  ),
}));
function message(paths: unknown = ["site/index.html", "site/style.css"]): ChatMessage {
  const source = env.source;
  const id = crypto.randomUUID();
  if (source?.kind === "local") useWorkOnStore.getState().rememberFileRoot(id, source.root);
  return {
    id: "m",
    role: "assistant",
    content: "Done",
    timestamp: new Date(),
    conversationId: "c1",
    fileSource:
      source?.kind === "local"
        ? { kind: "local", id }
        : source?.kind === "conversation"
          ? source
          : undefined,
    toolCalls: [
      {
        id: "tc",
        name: "run_coding_agent",
        args: {},
        status: "completed",
        result: JSON.stringify({ files_changed: paths }),
      },
    ],
  };
}
beforeEach(() => {
  env.source = { kind: "conversation", id: "c1" };
  env.access.mockReset();
});
it("opens exact paths from a completed turn and navigates the reported file set", async () => {
  render(<TurnFiles message={message()} />);
  await userEvent.click(screen.getByRole("button", { name: "site/index.html" }));
  expect(env.access).toHaveBeenLastCalledWith(env.source, "site/index.html");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(env.access).toHaveBeenLastCalledWith(env.source, "site/style.css");
  await userEvent.click(screen.getByRole("button", { name: "Outside" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("site/style.css");
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("does not offer files for user messages, a streaming turn, missing reports or an unavailable source", () => {
  const base = message();
  const view = render(<TurnFiles message={{ ...base, role: "user" }} />);
  expect(screen.queryByRole("button")).toBeNull();
  view.rerender(<TurnFiles message={{ ...base, isStreaming: true }} />);
  expect(screen.queryByRole("button")).toBeNull();
  view.rerender(<TurnFiles message={message([])} />);
  expect(screen.queryByRole("button")).toBeNull();
  env.source = null;
  const missing = message();
  delete missing.fileSource;
  view.rerender(<TurnFiles message={missing} />);
  expect(screen.queryByRole("button")).toBeNull();
});
it("resolves local paths only inside the chosen folder and keeps duplicate basenames distinct", async () => {
  env.source = { kind: "local", root: "/approved/" };
  render(
    <TurnFiles
      message={message([
        "/approved/index.html",
        "site/index.html",
        "/other/private.txt",
        "../private.txt",
        "/approved/../private.txt",
        "C:\\other\\private.txt",
      ])}
    />,
  );
  expect(screen.getByRole("button", { name: "index.html" })).toBeVisible();
  expect(screen.getByRole("button", { name: "site/index.html" })).toBeVisible();
  expect(screen.queryByText(/private/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "index.html" }));
  expect(env.access).toHaveBeenLastCalledWith(env.source, "index.html");
});
it("draws nothing when every reported local path is outside the selected folder", () => {
  env.source = { kind: "local", root: "/approved" };
  render(<TurnFiles message={message(["/other/a"])} />);
  expect(screen.queryByRole("button")).toBeNull();
});

it("keeps a turn linked to its original folder when Work on changes", async () => {
  env.source = { kind: "local", root: "/original" };
  const original = message(["index.html"]);
  const view = render(<TurnFiles message={original} />);
  env.source = { kind: "local", root: "/different" };
  view.rerender(<TurnFiles message={original} />);
  await userEvent.click(screen.getByRole("button", { name: "index.html" }));
  expect(env.access).toHaveBeenLastCalledWith({ kind: "local", root: "/original" }, "index.html");
});

it("keeps cloud links on their historical origin after switching to local work", async () => {
  env.source = { kind: "conversation", id: "original-chat" };
  const original = message(["index.html"]);
  env.source = { kind: "local", root: "/local" };
  render(<TurnFiles message={original} />);
  await userEvent.click(screen.getByRole("button", { name: "index.html" }));
  expect(env.access).toHaveBeenLastCalledWith(
    { kind: "conversation", id: "original-chat" },
    "index.html",
  );
});
