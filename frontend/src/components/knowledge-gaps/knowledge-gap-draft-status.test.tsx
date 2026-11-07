import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftStatus } from "./knowledge-gap-draft-status";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const TOPIC: KnowledgeGapTopic = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "parental leave",
  question_count: 2,
  asker_count: 2,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  covered_at: null,
  covered_by: null,
  has_draft: false,
  can_edit: true,
};

function renderStatus(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("KnowledgeGapDraftStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ total_usd: "0.0123" });
  });

  it("offers a draft with what it costs, and says it is drafting once asked", async () => {
    let finish: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderStatus(<KnowledgeGapDraftStatus topic={TOPIC} editable />);
    const button = await screen.findByRole("button", { name: "Draft · $0.0123" });
    expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps/t1/draft/estimate");

    await userEvent.click(button);
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/draft");
    expect(screen.getByRole("status")).toHaveTextContent("Drafting…");
    expect(screen.queryByRole("button")).toBeNull();
    finish({ ...TOPIC, drafting: true, questions: [], draft: null });
  });

  it("offers the draft before its cost is known", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    renderStatus(<KnowledgeGapDraftStatus topic={TOPIC} editable />);
    expect(screen.getByRole("button", { name: "Draft" })).toBeInTheDocument();
  });

  it("offers the draft without a cost when the model has none, or the estimate fails", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ total_usd: null });
    const { unmount } = renderStatus(<KnowledgeGapDraftStatus topic={TOPIC} editable />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Draft" })).toBeEnabled();
    unmount();
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Forbidden"));
    renderStatus(<KnowledgeGapDraftStatus topic={TOPIC} editable />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Draft" })).toBeEnabled();
  });

  it("announces a draft being written, with nothing to click", () => {
    renderStatus(<KnowledgeGapDraftStatus topic={{ ...TOPIC, drafting: true }} editable />);
    expect(screen.getByRole("status")).toHaveTextContent("Drafting…");
    expect(screen.queryByRole("button")).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("says a draft failed and asks for another on Try again", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...TOPIC, drafting: true });
    renderStatus(<KnowledgeGapDraftStatus topic={{ ...TOPIC, draft_failed: true }} editable />);
    expect(screen.getByRole("alert")).toHaveTextContent("The draft could not be written.");
    expect(screen.queryByRole("button", { name: /^Draft/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/draft");
  });

  it("marks a draft the knowledge base moved past, and offers a new one with its cost", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...TOPIC, drafting: true });
    renderStatus(
      <KnowledgeGapDraftStatus topic={{ ...TOPIC, has_draft: true, draft_stale: true }} editable />,
    );
    expect(screen.getByText("The knowledge base changed after this draft")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Redraft · $0.0123" }));
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/draft");
  });

  it("needs nothing for a current draft unless a new one is offered", async () => {
    const drafted = { ...TOPIC, has_draft: true };
    const { container, unmount } = renderStatus(
      <KnowledgeGapDraftStatus topic={drafted} editable />,
    );
    expect(container).toBeEmptyDOMElement();
    unmount();
    renderStatus(<KnowledgeGapDraftStatus topic={drafted} editable offerRedraft />);
    expect(await screen.findByRole("button", { name: "Redraft · $0.0123" })).toBeInTheDocument();
  });

  it("shows where a draft stands, without buttons, to somebody who may not draft", () => {
    const { rerender } = renderStatus(
      <KnowledgeGapDraftStatus topic={{ ...TOPIC, draft_failed: true }} editable={false} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The draft could not be written.");
    expect(screen.queryByRole("button")).toBeNull();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <KnowledgeGapDraftStatus
          topic={{ ...TOPIC, has_draft: true, draft_stale: true }}
          editable={false}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText("The knowledge base changed after this draft")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("shows nothing for a topic without a draft to somebody who may not draft", () => {
    const { container } = renderStatus(<KnowledgeGapDraftStatus topic={TOPIC} editable={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
