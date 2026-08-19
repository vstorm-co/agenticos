import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContextEditor } from "./context-editor";
import type { ContextFile } from "@/types/providers";

/**
 * Editing a context file, in the shape a skill is edited in: the facts in a
 * strip, the body in the shared pane, one footer.
 *
 * Two consequences the old flat form did not have, and both are asserted here.
 * The body is behind a preview/source toggle, so a test that types into it has
 * to ask for the source first - the way a person does. And Save is refused
 * while nothing has changed, so "an untouched field is not lost" is now proved
 * by changing one thing and reading the other four back.
 */

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

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

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
const openSource = () => userEvent.click(screen.getByRole("button", { name: "Source" }));
const body = () => screen.getByLabelText("glossary.md source");

describe("ContextEditor", () => {
  it("names the file with the format it is stored in, so the body renders as one", () => {
    // The name carries no extension and the format is a separate field, but the
    // renderer is chosen from a filename - so `glossary` alone read as plain
    // text where the agent receives Markdown.
    mount();

    expect(screen.getByText("glossary.md")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("reads the body rendered, and edits it behind the toggle", async () => {
    mount();
    expect(screen.getByTestId("rendered")).toHaveTextContent("SLA: service level agreement.");

    await openSource();

    expect(body()).toHaveValue("SLA: service level agreement.");
  });

  it("saves the whole editable set, so an untouched field is not lost", async () => {
    const { onSave } = mount();

    await openSource();
    await userEvent.type(body(), " extra");
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith({
      description: "terms",
      content: "SLA: service level agreement. extra",
      format: "md",
      mode: "inject",
      enabled: true,
    });
  });

  it("refuses a save that would write nothing", () => {
    mount();

    expect(save()).toBeDisabled();
  });

  it("says what a save reaches, once there is something to save", async () => {
    mount();
    expect(screen.queryByText(/Saving reaches every agent/)).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Description"), " and acronyms");

    expect(screen.getByText(/Saving reaches every agent/)).toBeInTheDocument();
  });

  it("sends an emptied description as null", async () => {
    const { onSave } = mount();

    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ description: null }));
  });

  it("takes the format from a closed list rather than from typing", async () => {
    // It was a text input, so `markdown`, `MD` and a typo were all accepted and
    // only one of them decided how the body renders.
    const { onSave } = mount();

    await userEvent.click(screen.getByLabelText("Format"));
    await userEvent.click(await screen.findByRole("option", { name: "txt" }));
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ format: "txt" }));
  });

  it("keeps a format the catalog does not list, rather than showing none", async () => {
    // The column took free text before the select did, so a stored `html` has to
    // remain both visible and unchanged - deciding it "really means md" would
    // make opening a file an edit.
    mount({ file: { ...FILE, format: "html" } });

    expect(screen.getByLabelText("Format")).toHaveTextContent("html");
    expect(save()).toBeDisabled();
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

    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ description: null }));
  });

  it("cancels without saving", async () => {
    const { onSave, onCancel } = mount();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("gives a viewer a way out and nothing to write with", async () => {
    mount({ canEdit: false });

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    await openSource();
    expect(body()).toHaveAttribute("readonly");
  });
});
