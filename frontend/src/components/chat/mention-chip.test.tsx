import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Mentionable } from "@/types/mention";
import { MentionChip } from "./mention-chip";

vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ slug }: { slug: string }) => <span data-testid="face">{slug}</span>,
}));

describe("a mention chip", () => {
  it.each<[Mentionable, string]>([
    [{ kind: "collection", id: "k", name: "Contracts" }, "lucide-database"],
    [{ kind: "skill", id: "s", name: "refunds" }, "lucide-book-open"],
    [{ kind: "context", id: "c", name: "glossary" }, "lucide-file-text"],
  ])("draws what kind of thing %o is", (item, icon) => {
    const { container } = render(<MentionChip item={item} />);
    expect(container.querySelector(`.${icon}`)).not.toBeNull();
    expect(screen.getByTitle(item.name)).toHaveTextContent(item.name);
  });

  it("draws an agent's face, by its handle or its name", () => {
    render(
      <>
        <MentionChip item={{ kind: "agent", id: "a", name: "Writer", slug: "writer" }} />
        <MentionChip item={{ kind: "agent", id: "b", name: "Reviewer" }} />
      </>,
    );
    expect(screen.getAllByTestId("face").map((face) => face.textContent)).toEqual([
      "writer",
      "Reviewer",
    ]);
  });

  it("is taken back only where it is offered", async () => {
    const onRemove = vi.fn();
    const item: Mentionable = { kind: "mcp", id: "g", name: "GitHub", detail: "github_*" };
    const { rerender } = render(<MentionChip item={item} onRemove={onRemove} />);
    await userEvent.click(screen.getByRole("button", { name: "Remove GitHub" }));
    expect(onRemove).toHaveBeenCalled();

    rerender(<MentionChip item={item} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByTitle("github_*")).toBeInTheDocument();
  });
});
