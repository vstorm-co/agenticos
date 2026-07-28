import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillWorkbench } from "./skill-workbench";
import type { Skill } from "@/types/providers";

// The workbench reaches for the file mutations it offers beside the body. None
// of them is exercised here — what these tests are about is the skill itself.
vi.mock("@/hooks", () => ({
  useSkill: () => ({
    addResource: { isPending: false, mutateAsync: vi.fn() },
    saveResource: { isPending: false, mutate: vi.fn() },
    removeResource: { mutateAsync: vi.fn() },
    uploadResources: { mutateAsync: vi.fn() },
  }),
  useSkillResource: () => ({ resource: undefined, isLoading: false }),
}));

const SKILL: Skill = {
  id: "skill-1",
  name: "refund-policy",
  description: "How refunds and their exceptions are handled.",
  content: "## Refunds\n\nWithin 30 days, no questions asked.",
  enabled: true,
  version: 3,
  visibility: "organization",
  owner_user_id: null,
  resources: [],
};

function renderWorkbench(props: Partial<React.ComponentProps<typeof SkillWorkbench>> = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  const workbench = (overrides: Partial<React.ComponentProps<typeof SkillWorkbench>>) => (
    <SkillWorkbench
      skill={SKILL}
      canEdit
      isSaving={false}
      onSave={onSave}
      onCancel={onCancel}
      {...props}
      {...overrides}
    />
  );
  const { rerender } = render(workbench({}));
  return {
    onSave,
    onCancel,
    update: (overrides: Partial<React.ComponentProps<typeof SkillWorkbench>>) =>
      rerender(workbench(overrides)),
  };
}

const description = () => screen.getByLabelText("Description");

/**
 * The body's editor, which lives behind the Source toggle.
 *
 * `SKILL.md` is Markdown and opens rendered, like every other Markdown file in
 * the skill — reading it as raw asterisks was the odd one out. Editing it is a
 * deliberate second step.
 */
async function content() {
  const source = screen.getByRole("button", { name: "Source" });
  if (source.getAttribute("aria-pressed") !== "true") await userEvent.click(source);
  return screen.getByLabelText("SKILL.md source");
}
const save = () => screen.getByRole("button", { name: "Save" });

describe("SkillWorkbench", () => {
  it("opens on the skill as it is stored", async () => {
    renderWorkbench();
    expect(description()).toHaveValue(SKILL.description);
    expect(await content()).toHaveValue(SKILL.content);
    expect(screen.getByRole("switch", { name: "Enabled" })).toBeChecked();
  });

  it("cannot be saved until something is actually different", async () => {
    renderWorkbench();
    expect(save()).toBeDisabled();
    await userEvent.type(description(), " Updated.");
    expect(save()).toBeEnabled();
  });

  it("says who an edit reaches, before it is saved rather than after", async () => {
    renderWorkbench();
    // The blast radius is the thing people get wrong about skills: there is no
    // draft, so the warning has to arrive while the save is still avoidable.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.type(await content(), "!");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Saving reaches every agent bound to this skill on its next run.",
    );
  });

  it("hands back the edited skill, not a patch of it", async () => {
    const { onSave } = renderWorkbench();
    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer disputes a charge.");
    await userEvent.click(screen.getByRole("switch", { name: "Enabled" }));
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith({
      description: "When a customer disputes a charge.",
      content: SKILL.content,
      enabled: false,
    });
  });

  it("refuses to save a skill the model would have nothing to go on", async () => {
    renderWorkbench();
    await userEvent.clear(description());
    expect(save()).toBeDisabled();
  });

  it("stops a second save while the first is in flight", async () => {
    const { update } = renderWorkbench();
    await userEvent.type(description(), " Updated.");
    expect(save()).toBeEnabled();
    update({ isSaving: true });
    expect(save()).toBeDisabled();
  });

  it("lets a viewer read the body but offers them nothing to change it with", async () => {
    renderWorkbench({ canEdit: false });
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(await content()).toHaveValue(SKILL.content);
    expect(await content()).toHaveAttribute("readonly");
    expect(description()).toHaveAttribute("readonly");
    expect(screen.getByRole("switch", { name: "Enabled" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("leaves a viewer's edits impossible even by typing", async () => {
    const { onSave } = renderWorkbench({ canEdit: false });
    await userEvent.type(await content(), "sneaky");
    expect(await content()).toHaveValue(SKILL.content);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("abandons the edit when cancelled", async () => {
    const { onSave, onCancel } = renderWorkbench();
    await userEvent.type(description(), " changed");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
