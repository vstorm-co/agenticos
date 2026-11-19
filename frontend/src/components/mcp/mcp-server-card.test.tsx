import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { McpServerCard } from "./mcp-server-card";

it("keeps server actions separate from opening its resource card", () => {
  const open = vi.fn();
  const connect = vi.fn();
  render(
    <McpServerCard
      name="Team tools"
      icon={null}
      url={null}
      description="Search shared documents"
      status="Connected"
      onOpen={open}
      actions={<button onClick={connect}>Manage accounts</button>}
    />,
  );
  fireEvent.click(screen.getByText("Search shared documents"));
  expect(open).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Manage accounts" }));
  expect(connect).toHaveBeenCalledOnce();
  expect(open).toHaveBeenCalledOnce();
});
