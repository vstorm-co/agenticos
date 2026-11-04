import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentSourceField } from "./agent-source-field";
vi.mock("@/components/workflows/pickers/agent-version-picker", () => ({
  AgentVersionPicker: ({ onChange }: { onChange: (value: unknown) => void }) => (
    <button onClick={() => onChange({ agent_id: "a1", version_id: "v1" })}>choose</button>
  ),
}));
describe("AgentSourceField", () => {
  it("only offers the catalog and preserves other settings", async () => {
    const onChange = vi.fn();
    render(<AgentSourceField config={{ max_cost_usd: 1 }} onChange={onChange} />);
    expect(screen.queryByRole("tab")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "choose" }));
    expect(onChange).toHaveBeenCalledWith({
      max_cost_usd: 1,
      agent: { agent_id: "a1", version_id: "v1" },
    });
  });
  it("keeps legacy inline data until the user replaces it", async () => {
    const onChange = vi.fn();
    render(
      <AgentSourceField
        config={{ inline: { name: "Legacy" }, max_cost_usd: 2 }}
        onChange={onChange}
      />,
    );
    expect(screen.getByText(/previously configured/)).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "choose" }));
    expect(onChange).toHaveBeenCalledWith({
      max_cost_usd: 2,
      agent: { agent_id: "a1", version_id: "v1" },
    });
  });
});
