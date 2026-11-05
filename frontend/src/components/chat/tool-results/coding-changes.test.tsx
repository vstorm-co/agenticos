import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TaskChanges } from "./coding-changes";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { ChangedFile, CodingTaskChanges } from "@/lib/coding-changes-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function file(overrides: Partial<ChangedFile>): ChangedFile {
  return {
    path: "app.py",
    old_path: null,
    status: "modified",
    additions: 0,
    deletions: 0,
    binary: false,
    patch: null,
    truncated: false,
    ...overrides,
  };
}

const APP_PY =
  "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n" +
  "@@ -1,2 +1,2 @@\n def total(a, b):\n-    return a - b\n+    return a + b\n";
const README =
  "diff --git a/README.md b/README.md\nnew file mode 100644\n--- /dev/null\n+++ b/README.md\n" +
  "@@ -0,0 +1 @@\n+# Demo\n\\ No newline at end of file\n";

function changes(overrides: Partial<CodingTaskChanges> = {}): CodingTaskChanges {
  return {
    id: "c-1",
    conversation_id: "conv-1",
    harness: "claude_code",
    files: [
      file({ path: "src/app.py", additions: 1, deletions: 1, patch: APP_PY }),
      file({ path: "README.md", status: "added", additions: 1, patch: README }),
    ],
    omitted: 0,
    truncated: false,
    created_at: "2026-11-04T00:00:00Z",
    ...overrides,
  };
}

function show(answer: CodingTaskChanges | Error | "pending") {
  if (answer === "pending") vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
  else if (answer instanceof Error) vi.mocked(apiClient.get).mockRejectedValue(answer);
  else vi.mocked(apiClient.get).mockResolvedValue(answer);
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <TaskChanges changeId="c-1" fallback={<p>names the harness gave</p>} />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("TaskChanges", () => {
  it("lists the two files a task edited, then exactly their two diffs", async () => {
    show(changes());

    expect(await screen.findByText("Changed 2 files")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Modified")).toBeInTheDocument();
    expect(screen.getByText("Added")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual([
      "src/app.py",
      "README.md",
    ]);
    expect(screen.getByText("return a - b")).toBeInTheDocument();
    expect(screen.getByText("return a + b")).toBeInTheDocument();
    expect(screen.getByText("# Demo")).toBeInTheDocument();
    expect(screen.getByText("No newline at end of file").closest("tr")).toHaveClass("italic");
    expect(screen.getByText("@@ -1,2 +1,2 @@")).toBeInTheDocument();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not listed/)).not.toBeInTheDocument();
    expect(screen.queryByText("names the harness gave")).not.toBeInTheDocument();
  });

  it("says so when the task changed nothing", async () => {
    show(changes({ files: [] }));
    expect(await screen.findByText("The task changed no files.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy patch" })).not.toBeInTheDocument();
  });

  it("marks a patch that was cut, and counts the files not listed", async () => {
    show(
      changes({
        files: [
          file({ path: "big.txt", additions: 900, patch: "@@ -0,0 +1 @@\n+a\n", truncated: true }),
          file({ path: "later.txt", additions: 3 }),
        ],
        omitted: 2,
        truncated: true,
      }),
    );

    expect(await screen.findByText("Changed 4 files")).toBeInTheDocument();
    expect(screen.getByText(/so it is cut short/)).toBeInTheDocument();
    expect(screen.getByText("2 more changed files are not listed.")).toBeInTheDocument();
    expect(screen.getAllByText("Past the patch's limit: only its name is kept.")).toHaveLength(1);
  });

  it("says files were left out without claiming the patch was cut", async () => {
    show(changes({ omitted: 3, truncated: true }));

    expect(await screen.findByText("3 more changed files are not listed.")).toBeInTheDocument();
    expect(screen.queryByText(/cut short/)).not.toBeInTheDocument();
  });

  it("calls a file cut before its first hunk cut, not unchanged", async () => {
    show(
      changes({
        files: [
          file({
            path: "big.txt",
            status: "added",
            patch: "diff --git a/big.txt b/big.txt\n\\ The patch was cut here.\n",
            truncated: true,
          }),
        ],
        truncated: true,
      }),
    );

    expect(
      await screen.findByText("Past the patch's limit: only its name is kept."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/did not change/)).not.toBeInTheDocument();
  });

  it("draws the start of a long file's diff and counts the rest", async () => {
    const lines = Array.from({ length: 450 }, (_, index) => `+line ${index}\n`).join("");
    show(
      changes({
        files: [
          file({
            path: "gen.txt",
            status: "added",
            additions: 450,
            patch: `@@ -0,0 +1,450 @@\n${lines}`,
          }),
        ],
      }),
    );

    expect(await screen.findByText("line 399")).toBeInTheDocument();
    expect(screen.queryByText("line 400")).not.toBeInTheDocument();
    expect(screen.getByText("50 more lines - Copy patch has them.")).toBeInTheDocument();
  });

  it("stops drawing lines once the change set has drawn its share", async () => {
    // Five files fill the budget at 400 lines each; the sixth draws none.
    const lines = Array.from({ length: 450 }, (_, index) => `+line ${index}\n`).join("");
    show(
      changes({
        files: Array.from({ length: 6 }, (_, index) =>
          file({
            path: `gen-${index}.txt`,
            status: "added",
            additions: 450,
            patch: `@@ -0,0 +1,450 @@\n${lines}`,
          }),
        ),
      }),
    );

    expect(await screen.findByText("Changed 6 files")).toBeInTheDocument();
    expect(screen.getAllByText("line 399")).toHaveLength(5);
    expect(screen.getAllByText("50 more lines - Copy patch has them.")).toHaveLength(5);
    expect(screen.getByText("450 more lines - Copy patch has them.")).toBeInTheDocument();
    expect(screen.queryByText(/did not change/)).not.toBeInTheDocument();
  });

  it("names a renamed, a binary and a mode-only file without inventing lines", async () => {
    show(
      changes({
        files: [
          file({
            path: "new.py",
            old_path: "old.py",
            status: "renamed",
            patch: "diff --git a/old.py b/new.py\nsimilarity index 100%\n",
          }),
          file({
            path: "logo.png",
            status: "added",
            binary: true,
            patch:
              "diff --git a/logo.png b/logo.png\nBinary files /dev/null and b/logo.png differ\n",
          }),
        ],
      }),
    );

    expect(await screen.findByText("old.py → new.py")).toBeInTheDocument();
    expect(screen.getByText("Renamed")).toBeInTheDocument();
    expect(screen.getByText("binary")).toBeInTheDocument();
    expect(screen.getByText("A binary file: there are no lines to show.")).toBeInTheDocument();
    expect(
      screen.getByText("Its content did not change: it was renamed, or its mode changed."),
    ).toBeInTheDocument();
  });

  it("copies the whole patch, every file's part in order", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    show(changes());

    await user.click(await screen.findByRole("button", { name: "Copy patch" }));

    expect(writeText).toHaveBeenCalledWith(APP_PY + README);
    expect(await screen.findByRole("button", { name: "Patch copied" })).toBeInTheDocument();
  });

  it("says it is loading, and says so when the change set cannot be read", async () => {
    const { unmount } = show("pending");
    expect(screen.getByText("Loading what the task changed…")).toBeInTheDocument();
    unmount();

    show(new ApiError(404, "Change set not found"));
    expect(
      await screen.findByText("What the task changed could not be loaded."),
    ).toBeInTheDocument();
    // A reader the diff is refused to still sees the names the harness gave.
    expect(screen.getByText("names the harness gave")).toBeInTheDocument();
  });
});
