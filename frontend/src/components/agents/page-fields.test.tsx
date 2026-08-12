import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PageFields } from "./page-fields";
import { DEFAULT_PAGE_CONFIG, type EmbedVariable, type PageConfig } from "@/types/embeds";

/**
 * The form behind a hosted page, field by field.
 *
 * The panel around it is tested in `embeds-panel.test.tsx`, which is where the
 * publish and the update land. What is left here is what each control does to the
 * config - because every one of them is the operator making a decision the page
 * cannot make for itself, and a control wired to the wrong key is a decision that
 * silently does not take.
 */

const onChange = vi.fn();

function fields(config: Partial<PageConfig> = {}, variables: EmbedVariable[] = []) {
  render(
    <PageFields
      config={{ ...DEFAULT_PAGE_CONFIG, ...config }}
      variables={variables}
      disabled={false}
      hasCustomLogo={false}
      onUpload={vi.fn()}
      onChange={onChange}
    />,
  );
}

beforeEach(() => onChange.mockClear());

describe("what the operator writes on the page", () => {
  it("carries the title", async () => {
    fields();

    await userEvent.type(screen.getByLabelText("Page title"), "R");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ title: "R" }));
  });

  it("carries the welcome message, written in a Markdown editor", async () => {
    // The same control "Context for this placement" uses. Three rows of a plain
    // textarea is a keyhole onto prose somebody is composing, and the page renders
    // this as Markdown, so the editor and the render agree about what it is.
    fields();

    await userEvent.type(screen.getByLabelText("Welcome message"), "H");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ welcome: "H" }));
  });

  it("carries an accent picked from the swatch", () => {
    // `fireEvent`, not `userEvent`: a colour input has no keyboard path to a value.
    fields();

    fireEvent.change(screen.getAllByLabelText("Accent colour")[0]!, {
      target: { value: "#123456" },
    });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ accent: "#123456" }));
  });

  it("carries an accent typed as hex", async () => {
    // Two controls, one value: somebody who knows the hex types it, and somebody
    // who does not picks it. Both write the same field.
    fields({ accent: "" });

    await userEvent.type(screen.getAllByLabelText("Accent colour")[1]!, "#");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ accent: "#" }));
  });
});

describe("what the page is allowed to offer", () => {
  it("carries a decision to drop the fresh-thread button", async () => {
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /fresh thread/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ allow_new_conversation: false }),
    );
  });

  it("carries a decision to let a visitor attach a file", async () => {
    // The only capability here that lets a stranger store something, which is why
    // it is off until somebody says otherwise.
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /attach a file/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ allow_files: true }));
  });

  it("carries a decision to offer a microphone", async () => {
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /A microphone/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ allow_voice: true }));
  });
});

describe("what the visitor is sent of the work", () => {
  it("carries a decision to stop narrating the steps", async () => {
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /What the agent is doing/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ show_tool_steps: false }));
  });

  it("carries a decision to open a step into what it returned", async () => {
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /What each step returned/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ show_tool_results: true }));
  });

  it("carries a decision to show the reasoning", async () => {
    fields();

    await userEvent.click(screen.getByRole("checkbox", { name: /The agent's reasoning/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ show_thinking: true }));
  });

  it("cannot be asked to open a step it is not sent", () => {
    fields({ show_tool_steps: false });

    expect(screen.getByRole("checkbox", { name: /What each step returned/ })).toBeDisabled();
  });
});

describe("the picture", () => {
  it("carries the choice of which image the page shows", async () => {
    fields();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "The organization's avatar" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ logo: "organization" }));
  });

  it("offers the upload only once a picture of its own is the choice", () => {
    fields({ logo: "agent" });

    expect(screen.queryByRole("button", { name: /Upload a picture/ })).toBeNull();
  });

  it("sends the chosen file", async () => {
    const onUpload = vi.fn();
    render(
      <PageFields
        config={{ ...DEFAULT_PAGE_CONFIG, logo: "custom" }}
        variables={[]}
        disabled={false}
        hasCustomLogo={false}
        onUpload={onUpload}
        onChange={onChange}
      />,
    );

    const file = new File(["x"], "logo.png", { type: "image/png" });
    const picker = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(picker, file);

    expect(onUpload).toHaveBeenCalledWith(file);
    // Cleared, so choosing the same file again fires again - which is what
    // somebody does after a refused upload.
    expect(picker.value).toBe("");
  });

  it("opens the picker from the button rather than showing a raw file input", async () => {
    render(
      <PageFields
        config={{ ...DEFAULT_PAGE_CONFIG, logo: "custom" }}
        variables={[]}
        disabled={false}
        hasCustomLogo
        onUpload={vi.fn()}
        onChange={onChange}
      />,
    );
    const picker = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clicked = vi.spyOn(picker, "click");

    await userEvent.click(screen.getByRole("button", { name: "Replace the picture" }));

    expect(clicked).toHaveBeenCalled();
  });
});

describe("a promise the surface cannot keep", () => {
  it("names a required variable that no URL may supply", () => {
    // A page's own URL is the only source of a value here, so required-and-not-
    // URL-safe is structurally unkeepable. The backend refuses it; saying so here
    // is what stops somebody meeting that refusal.
    fields({}, [{ name: "plan", required: true, description: "", url_safe: false }]);

    expect(screen.getByText(/plan/)).toBeInTheDocument();
  });
});
