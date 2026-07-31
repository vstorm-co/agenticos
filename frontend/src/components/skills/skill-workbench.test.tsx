import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillWorkbench } from "./skill-workbench";
import type { Skill } from "@/types/providers";

// The file mutations the workbench offers beside the body, held where a test can
// both drive them and read what they were asked to do.
const skillHooks = vi.hoisted(() => ({
  addResource: { isPending: false, mutateAsync: vi.fn(async () => undefined) },
  saveResource: { isPending: false, mutate: vi.fn() },
  removeResource: { mutateAsync: vi.fn(async () => undefined) },
  uploadResources: { mutateAsync: vi.fn(async () => undefined) },
  loaded: { resource: undefined as { content: string } | undefined, isLoading: false },
}));

vi.mock("@/hooks", () => ({
  useSkill: () => skillHooks,
  useSkillResource: () => skillHooks.loaded,
}));

beforeEach(() => {
  vi.clearAllMocks();
  skillHooks.addResource.isPending = false;
  skillHooks.saveResource.isPending = false;
  skillHooks.loaded.resource = undefined;
  skillHooks.loaded.isLoading = false;
});

const SKILL: Skill = {
  id: "skill-1",
  name: "refund-policy",
  description: "How refunds and their exceptions are handled.",
  content: "## Refunds\n\nWithin 30 days, no questions asked.",
  category: null,
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
 * the skill - reading it as raw asterisks was the odd one out. Editing it is a
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
      category: null,
    });
  });

  it("puts the skill on a shelf, trimmed to what the listing will show", async () => {
    // A shelf nobody suggested: the select's way out is "New category…", and
    // what is typed there is as valid as anything picked.
    const { onSave } = renderWorkbench();
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), " support ");
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ category: "support" }));
  });

  it("takes a skill off its shelf when the category is cleared", async () => {
    // Null, not the empty string: "" is a category the backend refuses, and a
    // skill without one is uncategorized rather than categorized-as-nothing.
    const { onSave } = renderWorkbench({ skill: { ...SKILL, category: "support" } });
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "No category" }));
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ category: null }));
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
    expect(screen.getByLabelText("Category")).toHaveAttribute("readonly");
    expect(screen.getByRole("switch", { name: "Enabled" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("leaves a viewer's edits impossible even by typing", async () => {
    const { onSave } = renderWorkbench({ canEdit: false });
    await userEvent.type(await content(), "sneaky");
    expect(await content()).toHaveValue(SKILL.content);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows a viewer the shelf's name, humanised, rather than the stored slug", async () => {
    renderWorkbench({ skill: { ...SKILL, category: "devops" }, canEdit: false });

    expect(screen.getByLabelText("Category")).toHaveValue("Devops");
  });

  it("leaves the new-category field on Escape without taking what was typed", async () => {
    // The way out of a field that only exists because "New category…" was
    // clicked. Blur does it too; a keyboard user has no blur to give.
    renderWorkbench();
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));

    await userEvent.type(screen.getByLabelText("Category"), "support{Escape}");

    // Back to the select, which is a combobox rather than a text box.
    expect(screen.getByRole("combobox", { name: "Category" })).toBeInTheDocument();
  });

  it("abandons the edit when cancelled", async () => {
    const { onSave, onCancel } = renderWorkbench();
    await userEvent.type(description(), " changed");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});

/**
 * The files beside the body.
 *
 * A skill is a folder, so `SKILL.md` sits in the tree with everything else and
 * the pane shows whichever one is open. The rules that are easy to break: the
 * body is what an unselected tree shows (not a blank pane), opening a file
 * leaves the unsaved body alone, and deleting the open file has to return the
 * pane to the body rather than to a resource that is gone.
 */
describe("the skill's files", () => {
  const FILE = {
    id: "r-1",
    name: "references/workflows.md",
    description: "The escalation ladder.",
    size_bytes: 2048,
  };

  const withFile = { ...SKILL, resources: [FILE] };

  it("shows the body when nothing in the tree is selected", () => {
    renderWorkbench({ skill: withFile });

    expect(screen.getByRole("button", { name: /SKILL\.md/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("opens a file from the tree into the pane", async () => {
    skillHooks.loaded.resource = { content: "1. Ask. 2. Escalate." };
    renderWorkbench({ skill: withFile });

    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    expect(screen.getByRole("treeitem", { selected: true })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByLabelText("references/workflows.md source")).toHaveValue(
      "1. Ask. 2. Escalate.",
    );
  });

  it("keeps an unsaved body while somebody reads a file", async () => {
    // The body's state is seeded once. Losing it on a tree click would discard
    // typing with no undo and no warning.
    skillHooks.loaded.resource = { content: "anything" };
    renderWorkbench({ skill: withFile });
    await userEvent.type(await content(), "\n\nExcept gift cards.");

    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    await userEvent.click(screen.getByRole("button", { name: /SKILL\.md/ }));

    expect(await content()).toHaveValue(`${SKILL.content}\n\nExcept gift cards.`);
  });

  it("saves a file's edit against that file's id", async () => {
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    await userEvent.type(screen.getByLabelText("references/workflows.md source"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save file" }));

    expect(skillHooks.saveResource.mutate).toHaveBeenCalledWith({ id: "r-1", content: "old!" });
  });

  it("returns to the body after the open file is deleted", async () => {
    // Otherwise the pane keeps rendering a resource the skill no longer has.
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    await userEvent.click(screen.getByRole("button", { name: "Remove references/workflows.md" }));

    expect(skillHooks.removeResource.mutateAsync).toHaveBeenCalledWith("r-1");
    expect(screen.getByRole("button", { name: /SKILL\.md/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("adds a file, and closes the form once it is added", async () => {
    renderWorkbench({ skill: withFile });

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "references/refunds.md");
    await userEvent.type(screen.getByLabelText("File contents"), "Within 30 days.");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    expect(skillHooks.addResource.mutateAsync).toHaveBeenCalledWith({
      name: "references/refunds.md",
      description: null,
      content: "Within 30 days.",
    });
    expect(screen.queryByLabelText("Path")).toBeNull();
  });

  it("abandons a new file when the form is cancelled", async () => {
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "New" }));

    // The form's own Cancel, not the dialog footer's.
    const form = screen.getByLabelText("Path").closest("form")!;
    await userEvent.click(within(form).getByRole("button", { name: "Cancel" }));

    expect(skillHooks.addResource.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Path")).toBeNull();
  });

  it("closes the new-file form when the body is selected instead", async () => {
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "New" }));

    await userEvent.click(screen.getByRole("button", { name: /SKILL\.md/ }));

    expect(screen.queryByLabelText("Path")).toBeNull();
  });

  it("closes the new-file form when a file is opened instead", async () => {
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "New" }));

    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    expect(screen.queryByLabelText("Path")).toBeNull();
  });

  it("uploads the files that were picked", async () => {
    renderWorkbench({ skill: withFile });
    const picked = new File(["a"], "checklist.md", { type: "text/markdown" });

    await userEvent.upload(screen.getByLabelText("Files"), picked);

    expect(skillHooks.uploadResources.mutateAsync).toHaveBeenCalledWith([picked]);
  });

  it("asks for nothing when a picker is dismissed with no files", () => {
    renderWorkbench({ skill: withFile });

    // What a cancelled picker looks like: the change fires with an empty list.
    fireEvent.change(screen.getByLabelText("Folder"), { target: { files: [] } });

    expect(skillHooks.uploadResources.mutateAsync).not.toHaveBeenCalled();
  });

  it("offers a viewer no way to add, upload or delete a file", async () => {
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile, canEdit: false });

    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    expect(screen.queryByLabelText("Files")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save file" })).toBeNull();
  });
});
