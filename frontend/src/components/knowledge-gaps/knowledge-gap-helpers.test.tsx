import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeGapHelpers } from "./knowledge-gap-helpers";

vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: (kind: string) => ({
    agents: [
      {
        id: `${kind}-own`,
        name: `Chosen ${kind}`,
        system_key: null,
        current_version_id: "v1",
        status: "published",
        published_model: null,
      },
    ],
    isLoading: false,
    error: null,
  }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

const kb = { name: "Handbook", gap_drafter_agent_id: null, gap_classifier_agent_id: null };

describe("knowledge-base helper choices", () => {
  it("saves the classifier and drafter selected for this knowledge base", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<KnowledgeGapHelpers kb={kb} onSave={save} />);
    await userEvent.click(screen.getByRole("button", { name: "AI helpers" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByText("Gap classifier"));
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Run with" }));
    await userEvent.click(screen.getByRole("option", { name: "Chosen classifier" }));
    await userEvent.click(within(dialog).getByText("Gap drafter"));
    await userEvent.click(
      within(screen.getByRole("group", { name: "Gap drafter" })).getByRole("combobox", {
        name: "Run with",
      }),
    );
    await userEvent.click(screen.getByRole("option", { name: "Chosen drafter" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledWith({
      gap_classifier_agent_id: "classifier-own",
      gap_drafter_agent_id: "drafter-own",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the choices open and explains a refused save", async () => {
    render(
      <KnowledgeGapHelpers
        kb={kb}
        onSave={vi.fn().mockRejectedValue(new Error("Publish this helper first"))}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "AI helpers" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Publish this helper first");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
