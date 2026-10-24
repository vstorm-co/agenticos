import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SystemAgentChoice } from "./system-agent-choice";

const query = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: (kind: string) => {
    query(kind);
    return {
      agents: [
        {
          id: "seed",
          name: "Default",
          kind,
          system_key: "seeded",
          status: "published",
          current_version_id: "v1",
          published_model: null,
        },
        {
          id: "own",
          name: "My assistant",
          kind,
          system_key: null,
          status: "published",
          current_version_id: "v2",
          published_model: { label: "Private model" },
        },
        {
          id: "draft",
          name: "Unpublished assistant",
          kind,
          system_key: null,
          status: "draft",
          current_version_id: null,
          published_model: null,
        },
      ],
      isLoading: false,
      error: null,
    };
  },
}));

describe("a system agent selected where it runs", () => {
  it("loads only the right kind when expanded and passes the selected identity", async () => {
    query.mockClear();
    const change = vi.fn();
    render(<SystemAgentChoice kind="improver" value={null} onChange={change} />);
    expect(query).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Authoring assistant"));
    expect(query).toHaveBeenCalledWith("improver");
    await userEvent.click(screen.getByRole("combobox", { name: "Run with" }));
    expect(
      screen.getByRole("option", { name: "Unpublished assistant · Not published" }),
    ).toHaveAttribute("data-disabled");
    await userEvent.click(screen.getByRole("option", { name: "My assistant" }));
    expect(change).toHaveBeenCalledWith("own");
  });

  it("keeps a missing selection visible instead of adopting the default", async () => {
    render(<SystemAgentChoice kind="generator" value="deleted" onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Case generator"));
    expect(screen.getByText("Selected agent is unavailable")).toBeInTheDocument();
  });
});
