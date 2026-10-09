import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RemoteChangeBanner } from "./remote-change-banner";
import type { ChangeEvent } from "@/types/change-events";

const CHANGE: ChangeEvent = {
  organization_id: "org-1",
  resource: "agent",
  id: "agent-1",
  action: "updated",
  surface: "mcp",
  actor_user_id: "user-1",
  actor_name: "Ada Lovelace",
};

describe("RemoteChangeBanner", () => {
  it("names who changed it and through what, and leaves the choice to the editor", async () => {
    const onReload = vi.fn();
    const onKeepMine = vi.fn();
    render(<RemoteChangeBanner change={CHANGE} onReload={onReload} onKeepMine={onKeepMine} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ada Lovelace changed this over MCP while you were editing it.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Keep my changes" }));
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));

    expect(onKeepMine).toHaveBeenCalledTimes(1);
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
