import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContextEditor } from "./context-editor";
import type { ContextFile } from "@/types/providers";

const FILE: ContextFile = {
  id: "c1",
  name: "glossary",
  description: "terms",
  content: "SLA: service level agreement.",
  format: "md",
  mode: "inject",
  enabled: true,
  visibility: "organization",
  owner_user_id: null,
};

function mount(props: Partial<React.ComponentProps<typeof ContextEditor>> = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <ContextEditor
      file={FILE}
      canEdit
      isSaving={false}
      onSave={onSave}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onSave, onCancel };
}

const save = () => screen.getByRole("button", { name: "Save" });

describe("ContextEditor", () => {
  it("shows the name it cannot let you change", () => {
    mount();
    expect(screen.getByText("glossary")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("saves the whole editable set so an untouched field is not lost", async () => {
    const { onSave } = mount();
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith({
      description: "terms",
      content: "SLA: service level agreement.",
      format: "md",
      mode: "inject",
      enabled: true,
    });
  });

  it("carries an edit to the body and the mode through", async () => {
    const { onSave } = mount({ file: { ...FILE, mode: "link" } });
    await userEvent.type(screen.getByLabelText("Content"), " extra");
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ mode: "link", content: "SLA: service level agreement. extra" }),
    );
  });

  it("sends an emptied description as null and an emptied format as md", async () => {
    const { onSave } = mount();
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.clear(screen.getByLabelText("Format"));
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ description: null, format: "md" }),
    );
  });

  it("switches an injected file to linked through the mode select", async () => {
    const { onSave } = mount();
    await userEvent.click(screen.getByLabelText("Mode"));
    await userEvent.click(await screen.findByRole("option", { name: "linked" }));
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ mode: "link" }));
  });

  it("toggles the enabled switch", async () => {
    const { onSave } = mount();
    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
  });

  it("starts an editor for a file with no description without crashing", async () => {
    const { onSave } = mount({ file: { ...FILE, description: null } });
    await userEvent.click(save());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ description: null }));
  });

  it("cancels without saving", async () => {
    const { onSave, onCancel } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("gives a viewer no write controls", () => {
    mount({ canEdit: false });
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Content")).toBeDisabled();
  });
});
