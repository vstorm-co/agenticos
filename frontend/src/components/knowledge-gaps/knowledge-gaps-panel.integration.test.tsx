import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { Perm } from "@/types/permissions";
import { KnowledgeGapsPanel } from "./knowledge-gaps-panel";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));
const perms = new Set<string>();
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => perms.has(p) }),
}));

const TOPIC = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "How long is parental leave?",
  question_count: 3,
  asker_count: 1,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [
    { id: "a1", name: "HR helper", slug: "hr-helper", has_avatar: false, avatar_color: null },
  ],
  dismissed_at: null,
  covered_at: null,
  covered_by: null,
  has_draft: false,
  can_edit: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  perms.clear();
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint.startsWith("/knowledge-gaps/agents/a1")) {
      return Promise.resolve({ items: [TOPIC], total: 1, ungrouped: 0 });
    }
    if (endpoint === "/knowledge-gaps/t1") return Promise.resolve({ ...TOPIC, questions: [] });
    if (endpoint.startsWith("/datasets")) {
      return Promise.resolve({
        items: [
          { id: "d1", name: "leave questions", can_edit: true },
          { id: "d2", name: "someone else's", can_edit: false },
        ],
        total: 2,
      });
    }
    return Promise.reject(new Error(`unexpected ${endpoint}`));
  });
});

async function openTopic() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <KnowledgeGapsPanel scope={{ kind: "agent", id: "a1" }} />
    </QueryClientProvider>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /parental leave/ }));
  await screen.findByRole("heading", { name: "How long is parental leave?" });
}

describe("an agent's knowledge gaps, by what the caller may do", () => {
  it("lets a caller who only reads runs look, and change nothing", async () => {
    perms.add(Perm.runsView);
    await openTopic();
    expect(screen.queryByRole("button", { name: "More actions for this topic" })).toBeNull();
  });

  it("turns the topic into cases of a dataset the caller edits, and counts them", async () => {
    perms.add(Perm.runsView).add(Perm.datasetsView);
    vi.mocked(apiClient.post).mockResolvedValue({
      dataset_id: "d1",
      version: 2,
      added: 2,
      skipped: 1,
    });
    await openTopic();
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "More actions for this topic",
      }),
    );
    expect(screen.queryByRole("menuitem", { name: "Dismiss" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Add to dataset" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dataset", {
        dataset_id: "d1",
      }),
    );
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "2 cases added to leave questions, 1 question skipped",
      ),
    );
  });
});
