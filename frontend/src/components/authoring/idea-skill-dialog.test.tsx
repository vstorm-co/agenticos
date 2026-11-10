import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IdeaSkillDialog, skillSlug } from "./idea-skill-dialog";

const CHANGE = {
  name: "Refund Policy Summary",
  description: "Explain refunds",
  content: "Ask for the order first.",
  answers: 3,
};

function preview(change = CHANGE, onCreate = vi.fn().mockResolvedValue(true)) {
  const onOpenChange = vi.fn();
  render(<IdeaSkillDialog change={change} onCreate={onCreate} onOpenChange={onOpenChange} />);
  return { onCreate, onOpenChange };
}

describe("skillSlug", () => {
  it("writes a model's title in the skill library's name format", () => {
    expect(skillSlug("  Refund Policy: Summary! ")).toBe("refund-policy-summary");
    expect(skillSlug(`${"a".repeat(63)} b`)).toBe("a".repeat(63));
  });
});

describe("IdeaSkillDialog", () => {
  it("creates the skill as edited and closes", async () => {
    const { onCreate, onOpenChange } = preview();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByLabelText("Name")).toHaveValue("refund-policy-summary");
    await userEvent.clear(screen.getByLabelText("What it is for, in one sentence"));
    await userEvent.type(screen.getByLabelText("What it is for, in one sentence"), " Refunds ");
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    expect(onCreate).toHaveBeenCalledWith({
      name: "refund-policy-summary",
      description: "Refunds",
      content: "Ask for the order first.",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("warns on few answers and holds back a name the library would refuse", async () => {
    preview({ answers: 1 } as never);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Based on 1 answer. Check it before you create it.",
    );
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    await userEvent.type(screen.getByLabelText("Name"), "Returns");
    expect(screen.getByRole("button", { name: "Create skill" })).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "returns");
    await userEvent.type(screen.getByLabelText("What it is for, in one sentence"), "Returns");
    expect(screen.getByRole("button", { name: "Create skill" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("What the agent does"), "Ask first.");
    expect(screen.getByRole("button", { name: "Create skill" })).toBeEnabled();
  });

  it("says why it was refused and stays open, and closes on Cancel", async () => {
    const onCreate = vi.fn().mockRejectedValueOnce(new Error("A skill with this name exists"));
    const { onOpenChange } = preview({ ...CHANGE, answers: undefined } as never, onCreate);
    expect(screen.getByRole("status")).toHaveTextContent("Not based on any answer.");
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A skill with this name exists");
    onCreate.mockResolvedValueOnce(false);
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    expect(onOpenChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
