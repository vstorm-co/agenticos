import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/runs-api";

import { RunFiles } from "./run-files";

vi.mock("@/lib/workflows/runs-api", () => ({ downloadWorkflowRunFile: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const FILE = {
  id: "f1",
  filename: "report.csv",
  content_type: "text/csv",
  byte_size: 2048,
  producing_node_run_id: null,
  created_at: "2026-09-29T10:00:00Z",
};

beforeEach(() => vi.clearAllMocks());

describe("RunFiles", () => {
  it("says a run stored nothing", () => {
    render(<RunFiles runId="r" files={[]} />);
    expect(screen.getByText("This run has stored no files.")).toBeTruthy();
  });

  it("lists each file with its type and size, and saves one", async () => {
    vi.mocked(api.downloadWorkflowRunFile).mockResolvedValue();
    render(<RunFiles runId="r" files={[FILE, { ...FILE, id: "f2", filename: null }]} />);
    expect(screen.getByText("report.csv")).toBeTruthy();
    expect(screen.getAllByText(/text\/csv · 2/)).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Download report.csv" }));
    expect(api.downloadWorkflowRunFile).toHaveBeenCalledWith("r", FILE);
    expect(screen.getByRole("button", { name: "Download f2" })).toBeTruthy();
  });

  it("says why a file could not be saved", async () => {
    vi.mocked(api.downloadWorkflowRunFile).mockRejectedValue(new Error("gone"));
    render(<RunFiles runId="r" files={[FILE]} />);
    await userEvent.click(screen.getByRole("button", { name: "Download report.csv" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
