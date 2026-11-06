import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ToolCall } from "@/types";
import { ToolGroup } from "./tool-group";

const search = (id: string): ToolCall => ({
  id,
  name: "web_search",
  args: { query: id },
  status: "completed",
});

describe("consecutive tool groups", () => {
  it("keeps a single call as its own step", () => {
    render(
      <ToolGroup calls={[search("one")]} mcpServers={[]}>
        <p>One search</p>
      </ToolGroup>,
    );
    expect(screen.getByText("One search")).toBeVisible();
    expect(screen.queryByText("1 action")).toBeNull();
  });

  it("collapses repeated searches and keeps the group open as results arrive", async () => {
    const view = render(
      <ToolGroup calls={[search("Poland"), search("Norway")]} mcpServers={[]}>
        <p>Search results</p>
      </ToolGroup>,
    );
    expect(screen.getByText("2 actions")).toBeVisible();
    expect(screen.getByText("Search results")).not.toBeVisible();
    await userEvent.click(screen.getByText("2 actions"));
    expect(screen.getByText("Search results")).toBeVisible();
    view.rerender(
      <ToolGroup calls={[search("Poland"), search("Norway"), search("Australia")]} mcpServers={[]}>
        <p>Search results</p>
      </ToolGroup>,
    );
    expect(screen.getByText("3 actions")).toBeVisible();
    expect(screen.getByText("Search results")).toBeVisible();
  });

  it.each([
    ["awaiting_answer", "Waiting for an answer"],
    ["error", "Failed"],
  ] as const)("keeps a %s visible in a collapsed batch", (status, label) => {
    render(
      <ToolGroup calls={[search("one"), { ...search("two"), status }]} mcpServers={[]}>
        <p>Details</p>
      </ToolGroup>,
    );
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByText("Details")).not.toBeVisible();
  });

  it("keeps a mixed batch summary short while retaining every operation in its title", () => {
    const calls: ToolCall[] = [
      search("search"),
      ...["web_fetch", "read_file", "write_file"].map((name) => ({
        id: name,
        name,
        args: {},
        status: "completed" as const,
      })),
    ];
    const { container } = render(
      <ToolGroup calls={calls} mcpServers={[]}>
        <p>Four operations</p>
      </ToolGroup>,
    );
    const label = container.querySelector("summary [title]");
    expect(label?.textContent).toContain("…");
    expect(label?.getAttribute("title")?.split(", ")).toHaveLength(4);
    expect(screen.getByText("4 actions")).toBeVisible();
  });

  it("names mixed tools and surfaces a pending approval without expanding arguments", () => {
    render(
      <ToolGroup
        calls={[
          search("one"),
          { id: "write", name: "write_file", args: {}, status: "awaiting_approval" },
        ]}
        mcpServers={[]}
      >
        <p>Private arguments</p>
      </ToolGroup>,
    );
    expect(screen.getByText("Waiting for approval")).toBeVisible();
    expect(screen.getByText("Private arguments")).not.toBeVisible();
    expect(screen.getByText("2 actions")).toBeVisible();
  });
});

it("animates an executing batch and restores its object icon after completion", () => {
  const calls: ToolCall[] = [
    { ...search("one"), name: "agenticos_upsert_virtual_table_record" },
    { ...search("two"), status: "running" },
  ];
  const view = render(
    <ToolGroup calls={calls} mcpServers={[]}>
      Details
    </ToolGroup>,
  );
  expect(view.container.querySelector("summary .lucide-loader-circle")).toBeInTheDocument();
  expect(screen.getByText("Running")).toBeInTheDocument();
  view.rerender(
    <ToolGroup calls={calls.map((call) => ({ ...call, status: "completed" }))} mcpServers={[]}>
      Details
    </ToolGroup>,
  );
  expect(view.container.querySelector(".lucide-loader-circle")).toBeNull();
  expect(view.container.querySelector("summary .lucide-table-2")).toBeInTheDocument();
});
