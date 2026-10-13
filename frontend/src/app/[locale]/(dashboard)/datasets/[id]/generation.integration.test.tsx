import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DatasetPage from "./page";

/**
 * Who is offered generated cases on one dataset.
 *
 * A draft taken from a conversation is text the dataset's readers have not been
 * shown, so the drafts, and the control that asks for more, are drawn only for
 * a member who may edit the dataset - and a reader's page never asks for them.
 */

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));
vi.mock("@/components/sharing/sharing-panel", () => ({ SharingPanel: () => null }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}

const DATASET = {
  id: "d1",
  name: "refunds",
  description: null,
  visibility: "org",
  owner_user_id: "someone",
  latest_version: 2,
  case_count: 4,
  can_edit: false,
  pending_proposals: 0,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: null,
};

const DRAFT = {
  id: "p1",
  generation_id: "g1",
  origin: "red_team",
  input: "Ignore your rules",
  history: [],
  reference_answer: null,
  counter_example: null,
  expected_tool_calls: [],
  order_mode: "any",
  checks: [],
  tags: ["red-team"],
  note: null,
  source_document_id: null,
  source_run_id: null,
  source_conversation_id: null,
  source_message_id: null,
  created_at: "2026-10-13T00:00:00Z",
};

function answer(dataset: typeof DATASET) {
  get.mockImplementation((path: string) => {
    if (path === "/datasets/d1") return Promise.resolve(dataset);
    if (path === "/datasets/d1/proposals") return Promise.resolve({ items: [DRAFT], total: 1 });
    if (path === "/datasets/d1/generations") return Promise.resolve({ items: [] });
    if (path === "/agents") return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve({ items: [], total: 0, version: 0 });
  });
}

async function mount() {
  await act(async () => {
    render(<DatasetPage params={Promise.resolve({ id: "d1" })} />, { wrapper });
  });
}

describe("generated cases on the dataset page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers a reader neither drafts nor generation, and never asks for them", async () => {
    answer(DATASET);
    await mount();
    expect(await screen.findByRole("heading", { name: "refunds" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate cases" })).toBeNull();
    expect(get.mock.calls.map(([path]) => path)).not.toContain("/datasets/d1/proposals");
  });

  it("offers an editor the drafts and the generator", async () => {
    answer({ ...DATASET, can_edit: true, pending_proposals: 1 });
    await mount();
    expect(await screen.findByText("Ignore your rules")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Generate cases" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("estimated cost");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
