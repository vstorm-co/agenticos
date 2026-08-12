import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HostedPageFields } from "./hosted-page-fields";
import { DEFAULT_HOSTED_CONFIG, type EmbedVariable } from "@/types/embeds";

/**
 * The controls that turn an embed into a link somebody can send.
 *
 * The backend refuses two combinations - token auth, and a required variable a
 * URL cannot fill - so what this panel has to do is say why *before* the save.
 * A form that lets somebody assemble a refusal and then reports it is a form
 * that made them guess.
 */

function variable(overrides: Partial<EmbedVariable> = {}): EmbedVariable {
  return { name: "plan", required: false, description: "", url_safe: false, ...overrides };
}

function fields(overrides: Partial<Parameters<typeof HostedPageFields>[0]> = {}) {
  const props = {
    hosted: false,
    config: DEFAULT_HOSTED_CONFIG,
    authMode: "public",
    variables: [] as EmbedVariable[],
    disabled: false,
    onHostedChange: vi.fn(),
    onConfigChange: vi.fn(),
    ...overrides,
  };
  render(<HostedPageFields {...props} />);
  return props;
}

describe("hosting an embed as a page", () => {
  it("keeps the branding out of the way until hosting is on", () => {
    fields();

    expect(screen.queryByLabelText("Page title")).toBeNull();
  });

  it("offers the four branding fields once it is on", () => {
    fields({ hosted: true });

    expect(screen.getByLabelText("Page title")).toBeInTheDocument();
    expect(screen.getByLabelText("Welcome message")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Accent colour").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Logo")).toBeInTheDocument();
  });

  it("says plainly what a hosted link is protected by", () => {
    // The security stance #517 asks to be written down rather than defaulted:
    // the key, the rate limit, the budget and the pause switch - nothing else.
    fields({ hosted: true });

    expect(screen.getByText(/Anyone with the link can talk to this agent/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be guessed/)).toBeInTheDocument();
  });

  it("refuses to offer hosting for a token-authenticated embed, and says why", () => {
    // Not a disabled switch with no explanation: the reason is the whole point,
    // because the alternative somebody reaches for is the widget.
    fields({ authMode: "jwt" });

    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText(/token would travel in the URL/)).toBeInTheDocument();
  });

  it("names a required variable a URL cannot fill", () => {
    fields({
      hosted: true,
      variables: [variable({ name: "plan", required: true, url_safe: false })],
    });

    expect(screen.getByText(/Required and not URL-safe: plan/)).toBeInTheDocument();
  });

  it("says nothing about a required variable that is URL-safe", () => {
    fields({
      hosted: true,
      variables: [variable({ name: "plan", required: true, url_safe: true })],
    });

    expect(screen.queryByText(/Required and not URL-safe/)).toBeNull();
  });

  it("says nothing about an optional variable a URL cannot fill", () => {
    // It simply never arrives, which is what optional means.
    fields({ hosted: true, variables: [variable({ required: false, url_safe: false })] });

    expect(screen.queryByText(/Required and not URL-safe/)).toBeNull();
  });

  it("carries an edited title back to the caller", async () => {
    const props = fields({ hosted: true });

    await userEvent.type(screen.getByLabelText("Page title"), "R");

    expect(props.onConfigChange).toHaveBeenCalledWith({ ...DEFAULT_HOSTED_CONFIG, title: "R" });
  });

  it("takes the accent from the swatch as well as from the field", async () => {
    // Two controls, one value: a colour picked from the swatch and a hex typed
    // into the field have to reach the same place.
    const props = fields({ hosted: true });

    fireEvent.change(document.getElementById("hosted-accent")!, {
      target: { value: "#00ff00" },
    });
    expect(props.onConfigChange).toHaveBeenCalledWith({
      ...DEFAULT_HOSTED_CONFIG,
      accent: "#00ff00",
    });

    const field = screen.getAllByLabelText("Accent colour").at(-1)!;
    fireEvent.change(field, { target: { value: "#ff0000" } });
    expect(props.onConfigChange).toHaveBeenCalledWith({
      ...DEFAULT_HOSTED_CONFIG,
      accent: "#ff0000",
    });
  });

  it("carries the welcome message back to the caller", async () => {
    const props = fields({ hosted: true });

    await userEvent.type(screen.getByLabelText("Welcome message"), "H");

    expect(props.onConfigChange).toHaveBeenCalledWith({ ...DEFAULT_HOSTED_CONFIG, welcome: "H" });
  });

  it("carries a chosen logo back to the caller", async () => {
    const props = fields({ hosted: true });

    await userEvent.click(screen.getByLabelText("Logo"));
    await userEvent.click(screen.getByRole("option", { name: "No logo" }));

    expect(props.onConfigChange).toHaveBeenCalledWith({ ...DEFAULT_HOSTED_CONFIG, logo: "none" });
  });

  it("offers only images the platform already stores", async () => {
    // No URL field and no second upload path: an operator-supplied URL is a
    // third-party request from a page we serve.
    fields({ hosted: true });

    await userEvent.click(screen.getByLabelText("Logo"));

    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "The agent's avatar",
      "The organization's avatar",
      "No logo",
    ]);
  });

  it("switches hosting on through the caller rather than by itself", async () => {
    const props = fields();

    await userEvent.click(screen.getByRole("switch"));

    expect(props.onHostedChange).toHaveBeenCalledWith(true);
  });

  it("locks the fields while a publish is in flight", () => {
    fields({ hosted: true, disabled: true });

    expect(screen.getByLabelText("Page title")).toBeDisabled();
    expect(screen.getByLabelText("Welcome message")).toBeDisabled();
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
