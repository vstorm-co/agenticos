import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StartImprovementDialog } from "./start-improvement-dialog";

vi.mock("./start-session", () => ({
  StartSession: ({ agentId, onClose }: { agentId: string; onClose: () => void }) => (
    <button onClick={onClose}>{agentId}</button>
  ),
}));
const agent = { id: "a1", name: "Support", slug: "support", has_avatar: false, avatar_color: null };
describe("StartImprovementDialog", () => {
  it("opens the form with the agent identity and closes from its own controls", async () => {
    const close = vi.fn();
    render(<StartImprovementDialog agent={agent} allowed onClose={close} />);
    const dialog = screen.getByRole("dialog", { name: "Improve Support" });
    expect(dialog.querySelector('[data-agent-avatar="a1"]')).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "a1" }));
    expect(close).toHaveBeenCalled();
  });
  it("shows a refusal instead of mounting a form without authority", async () => {
    const close = vi.fn();
    render(<StartImprovementDialog agent={agent} allowed={false} onClose={close} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/Editing this agent/);
    expect(screen.queryByRole("button", { name: "a1" })).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    expect(close).toHaveBeenCalled();
  });
});
