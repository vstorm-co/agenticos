import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";

import { SkillWorkbench } from "./skill-workbench";
import type { Skill } from "@/types/providers";

// The file mutations the workbench offers beside the body, held where a test can
// both drive them and read what they were asked to do.
const skillHooks = vi.hoisted(() => ({
  addResource: { isPending: false, mutateAsync: vi.fn(async () => undefined) },
  saveResource: { isPending: false, mutateAsync: vi.fn(async () => undefined) },
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
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
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
  version: 3,
  latest_version_id: "v3",
  visibility: "organization",
  owner_user_id: null,
  resources: [],
};

function renderWorkbench(props: Partial<React.ComponentProps<typeof SkillWorkbench>> = {}) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const onCancel = vi.fn();
  const onFilesWritten = vi.fn();
  const workbench = (overrides: Partial<React.ComponentProps<typeof SkillWorkbench>>) => (
    <SkillWorkbench
      skill={SKILL}
      canEdit
      isSaving={false}
      saveWarning="Saving makes v4 on main."
      onSave={onSave}
      onFilesWritten={onFilesWritten}
      onCancel={onCancel}
      {...props}
      {...overrides}
    />
  );
  const { rerender } = render(workbench({}));
  return {
    onSave,
    onCancel,
    onFilesWritten,
    update: (overrides: Partial<React.ComponentProps<typeof SkillWorkbench>>) =>
      rerender(workbench(overrides)),
  };
}

const description = () => screen.getByLabelText("Description");

/**
 * The body's editor, which lives behind the Source toggle.
 *
 * The instructions are Markdown and open rendered, like every other Markdown file in
 * the skill - reading it as raw asterisks was the odd one out. Editing it is a
 * deliberate second step.
 */
async function content() {
  const source = screen.queryByRole("button", { name: "Source" });
  if (source) await userEvent.click(source);
  return screen.getByLabelText("Instructions source");
}
const save = () => screen.getByRole("button", { name: "Save" });

describe("SkillWorkbench", () => {
  it("opens on the skill as it is stored", async () => {
    renderWorkbench();
    expect(description()).toHaveValue(SKILL.description);
    expect(await content()).toHaveValue(SKILL.content);
    expect(screen.queryByRole("switch", { name: "Enabled" })).not.toBeInTheDocument();
  });

  it("cannot be saved until something is actually different", async () => {
    renderWorkbench();
    expect(save()).toBeDisabled();
    await userEvent.type(description(), " Updated.");
    expect(save()).toBeEnabled();
  });

  it("says who an edit reaches, before it is saved rather than after", async () => {
    renderWorkbench();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.type(await content(), "!");
    expect(screen.getByRole("alert")).toHaveTextContent("Saving makes v4 on main.");
  });

  it("keeps a fork's files and category read-only, since they are main's", async () => {
    renderWorkbench({ fork: true });
    expect(screen.queryByRole("button", { name: /New/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Category")).toHaveAttribute("readonly");
    await userEvent.type(await content(), "!");
    expect(save()).toBeEnabled();
  });

  it("hands back the edited skill, not a patch of it", async () => {
    const { onSave } = renderWorkbench();
    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer disputes a charge.");
    expect(screen.queryByRole("switch", { name: "Enabled" })).not.toBeInTheDocument();
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith({
      description: "When a customer disputes a charge.",
      content: SKILL.content,
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
    expect(screen.queryByRole("switch", { name: "Enabled" })).not.toBeInTheDocument();
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
 * A skill is a folder, so its instructions sit in the tree with everything else and
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

    expect(screen.getByRole("button", { name: "Instructions" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("opens a file from the tree into the pane", async () => {
    skillHooks.loaded.resource = { content: "1. Ask. 2. Escalate." };
    renderWorkbench({ skill: withFile });

    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    expect(screen.getByRole("treeitem", { selected: true })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    expect(useUnsavedChangesStore.getState().prompt).toBeNull();
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
    await userEvent.click(screen.getByRole("button", { name: "Instructions" }));

    expect(await content()).toHaveValue(`${SKILL.content}\n\nExcept gift cards.`);
  });

  it("asks before switching away from an edited resource", async () => {
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    const input = screen.getByLabelText("references/workflows.md source");
    await userEvent.type(input, " changed");
    await userEvent.click(screen.getByRole("button", { name: "Instructions" }));
    expect(input).toHaveValue("old changed");
    expect(useUnsavedChangesStore.getState().prompt).not.toBeNull();
    await act(() => useUnsavedChangesStore.getState().answer("stay"));
    expect(input).toHaveValue("old changed");
    await userEvent.click(screen.getByRole("button", { name: "Instructions" }));
    await act(() => useUnsavedChangesStore.getState().answer("discard"));
    expect(await content()).toHaveValue(SKILL.content);
  });

  it("saves a file's edit against that file's id", async () => {
    skillHooks.loaded.resource = { content: "old" };
    const { onFilesWritten } = renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    await userEvent.type(screen.getByLabelText("references/workflows.md source"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save file" }));

    expect(skillHooks.saveResource.mutateAsync).toHaveBeenCalledWith({
      id: "r-1",
      content: "old!",
    });
    expect(onFilesWritten).toHaveBeenCalledOnce();
  });

  it("returns to the body after the open file is deleted", async () => {
    // Otherwise the pane keeps rendering a resource the skill no longer has.
    skillHooks.loaded.resource = { content: "old" };
    const { onFilesWritten } = renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));

    await userEvent.click(screen.getByRole("button", { name: "Remove references/workflows.md" }));

    expect(skillHooks.removeResource.mutateAsync).toHaveBeenCalledWith("r-1");
    expect(onFilesWritten).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Instructions" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("adds a file, and closes the form once it is added", async () => {
    const { onFilesWritten } = renderWorkbench({ skill: withFile });

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
    expect(onFilesWritten).toHaveBeenCalledOnce();
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

    await userEvent.click(screen.getByRole("button", { name: "Instructions" }));

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
    const { onFilesWritten } = renderWorkbench({ skill: withFile });
    const picked = new File(["a"], "checklist.md", { type: "text/markdown" });

    await userEvent.upload(screen.getByLabelText("Files"), picked);

    expect(skillHooks.uploadResources.mutateAsync).toHaveBeenCalledWith([picked]);
    expect(onFilesWritten).toHaveBeenCalledOnce();
  });

  it("asks for nothing when a picker is dismissed with no files", () => {
    renderWorkbench({ skill: withFile });

    // What a cancelled picker looks like: the change fires with an empty list.
    fireEvent.change(screen.getByLabelText("Folder"), { target: { files: [] } });

    expect(skillHooks.uploadResources.mutateAsync).not.toHaveBeenCalled();
  });

  it("survives an upload the server refuses", async () => {
    // The mutation reports its own failure; what must not happen is an
    // unhandled rejection taking the workbench down with it.
    skillHooks.uploadResources.mutateAsync.mockRejectedValueOnce(new Error("413"));
    const { onFilesWritten } = renderWorkbench({ skill: withFile });

    await userEvent.upload(
      screen.getByLabelText("Files"),
      new File(["a"], "huge.md", { type: "text/markdown" }),
    );

    expect(screen.getByRole("button", { name: "Instructions" })).toBeInTheDocument();
    expect(onFilesWritten).not.toHaveBeenCalled();
  });

  it("keeps an open file and its draft when removal is refused", async () => {
    skillHooks.removeResource.mutateAsync.mockRejectedValueOnce(new Error("Removal refused"));
    skillHooks.loaded.resource = { content: "old" };
    renderWorkbench({ skill: withFile });
    await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
    const input = screen.getByLabelText("references/workflows.md source");
    await userEvent.type(input, " changed");
    await userEvent.click(screen.getByRole("button", { name: "Remove references/workflows.md" }));
    expect(input).toHaveValue("old changed");
    expect(useUnsavedChangesStore.getState().sources["skill-resource:skill-1:r-1"]).toBeDefined();
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

it("offers deletion from the editor's resource menu", async () => {
  const onDelete = vi.fn();
  renderWorkbench({ onDelete });
  await userEvent.click(screen.getByRole("button", { name: "More actions for refund-policy" }));
  expect(onDelete).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("menuitem", { name: "Delete refund-policy" }));
  expect(onDelete).toHaveBeenCalledOnce();
});

it("does not offer the resource menu to a reader", () => {
  renderWorkbench({ canEdit: false, onDelete: vi.fn() });
  expect(screen.queryByRole("button", { name: "More actions for refund-policy" })).toBeNull();
});

it("disables destructive actions while a save is pending", () => {
  renderWorkbench({ isSaving: true, onDelete: vi.fn() });
  expect(screen.getByRole("button", { name: "More actions for refund-policy" })).toBeDisabled();
});

it("blocks deleting a skill while one of its files is being added", () => {
  skillHooks.addResource.isPending = true;
  renderWorkbench({ onDelete: vi.fn() });
  expect(screen.getByRole("button", { name: "More actions for refund-policy" })).toBeDisabled();
});

it("reveals skill metadata without resetting its edited description", async () => {
  renderWorkbench();
  const toggle = screen.getByRole("button", { name: /^Description / });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  await userEvent.type(description(), " revised");
  await userEvent.click(toggle);
  await userEvent.click(toggle);
  expect(description()).toHaveValue(SKILL.description + " revised");
});

it("shows only one auxiliary panel and closes files after choosing a document", async () => {
  skillHooks.loaded.resource = { content: "reference" };
  renderWorkbench({
    skill: {
      ...SKILL,
      resources: [
        { id: "r-1", name: "references/workflows.md", description: "Reference", size_bytes: 2048 },
      ],
    },
  });
  const metadata = screen.getByRole("button", { name: /^Description / });
  const files = screen.getByRole("button", { name: "Files" });
  expect(files).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(metadata);
  await userEvent.click(files);
  expect(metadata).toHaveAttribute("aria-expanded", "false");
  expect(files).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(screen.getByRole("button", { name: "workflows.md" }));
  expect(files).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByLabelText("references/workflows.md source")).toHaveValue("reference");
});

it("places full view beside sharing in the bottom action group", async () => {
  const open = vi.fn();
  const { update } = renderWorkbench({ onOpenFull: open });
  const button = screen.getByRole("button", { name: "Open full view" });
  expect(button.parentElement).toHaveClass("mr-auto");
  await userEvent.click(button);
  expect(open).toHaveBeenCalledOnce();
  update({ isSaving: true });
  expect(button).toBeDisabled();
});

it("retains the skill draft after a refused navigation save", async () => {
  renderWorkbench({ onSave: vi.fn().mockRejectedValue(new Error("Refused")) });
  await userEvent.type(description(), " Changed");
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("save"));
  expect(proceed).not.toHaveBeenCalled();
  expect(description()).toHaveValue(`${SKILL.description} Changed`);
});

it("discards all skill metadata and instructions before leaving", async () => {
  const { onSave } = renderWorkbench();
  await userEvent.type(description(), " Changed");
  await userEvent.type(await content(), " Changed");
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(proceed).toHaveBeenCalledOnce();
  expect(description()).toHaveValue(SKILL.description);
  expect(await content()).toHaveValue(SKILL.content);
  expect(onSave).not.toHaveBeenCalled();
});
