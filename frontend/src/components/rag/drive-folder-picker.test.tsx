import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DriveFolderPicker } from "./drive-folder-picker";
import { apiClient } from "@/lib/api-client";
import type { DriveFolderList } from "@/lib/rag-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/** What the API answers for each `parent` the picker can ask for. */
const LEVELS: Record<string, DriveFolderList> = {
  root: {
    drives: [{ id: "0ABshared", name: "Handbook drive" }],
    folders: [{ id: "f-1", name: "Policies" }],
  },
  "drive:0ABshared": { drives: [], folders: [{ id: "f-9", name: "Onboarding" }] },
  "f-1": { drives: [], folders: [{ id: "f-2", name: "2026" }] },
};

function listed(parent: string | undefined): DriveFolderList {
  return LEVELS[parent ?? "root"] ?? { drives: [], folders: [] };
}

function renderPicker(onSelect = vi.fn(), value = "") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DriveFolderPicker account="account-1" value={value} onSelect={onSelect} />
    </QueryClientProvider>,
  );
  return { onSelect };
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockImplementation(async (...args: unknown[]) => {
    const options = args[1] as { params?: { parent?: string } } | undefined;
    return listed(options?.params?.parent);
  });
});

describe("the Drive folder picker", () => {
  it("shows My Drive's top level with the shared drives beside it, and nothing to select there", async () => {
    renderPicker();

    expect(await screen.findByRole("button", { name: "Policies" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Handbook drive" })).toBeVisible();
    expect(screen.getByText("Shared drives")).toBeVisible();
    // The root is not a folder a source can be pointed at, so it has no action.
    expect(screen.queryByRole("button", { name: "Select this folder" })).toBeNull();
  });

  it("walks into a folder and selects it by its id", async () => {
    const { onSelect } = renderPicker();

    await userEvent.click(await screen.findByRole("button", { name: "Policies" }));
    expect(await screen.findByRole("button", { name: "2026" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Select this folder" }));

    expect(onSelect).toHaveBeenCalledWith("f-1");
  });

  it("opens a shared drive at its own top level", async () => {
    renderPicker();

    await userEvent.click(await screen.findByRole("button", { name: "Handbook drive" }));

    expect(await screen.findByRole("button", { name: "Onboarding" })).toBeVisible();
    expect(apiClient.get).toHaveBeenLastCalledWith("/sync-sources/gdrive/folders", {
      params: { account: "account-1", parent: "drive:0ABshared" },
    });
  });

  it("shows a saved folder by its name only once that name has been browsed, never its raw id", async () => {
    renderPicker(vi.fn(), "f-1");

    expect(await screen.findByText("Syncing the selected folder")).toBeVisible();
    expect(screen.queryByText(/f-1/)).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: "Policies" }));

    expect(await screen.findByText("Syncing Policies")).toBeVisible();
  });

  it("says an empty level is empty", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ drives: [], folders: [] });
    renderPicker();

    expect(await screen.findByText("No folders here.")).toBeVisible();
  });

  it("answers a failed listing with the error and a retry that asks again", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Drive is unreachable"));
    renderPicker();

    expect(await screen.findByRole("alert")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: "Policies" })).toBeVisible();
  });
});
