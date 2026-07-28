import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ModelSettingsForm, PROVIDER_DEFAULT } from "./model-settings-form";
import type { ModelSettingsSpec } from "@/types/agents";

function renderForm(value: ModelSettingsSpec = {}, onChange = vi.fn(), disabled = false) {
  render(<ModelSettingsForm value={value} onChange={onChange} disabled={disabled} />);
  return onChange;
}

const temperature = () => screen.getByLabelText("Temperature");
const resetTemperature = () =>
  screen.getAllByRole("button", { name: "Use provider default" })[0] as HTMLElement;

/**
 * The Builder's half of "unset must stay unset".
 *
 * Everything here turns on one distinction the screen has to make honestly: a
 * setting nobody chose is not the same as one that happens to sit at the
 * provider's default. Sending the second where the first was meant is what
 * breaks an agent pointed at a reasoning model, which rejects `temperature`
 * outright.
 */
describe("ModelSettingsForm", () => {
  it("shows an untouched setting as the provider's, not as a number", () => {
    renderForm();
    // The slider has to point somewhere; the readout is what says whether the
    // position means anything.
    expect(screen.getAllByText(PROVIDER_DEFAULT).length).toBeGreaterThan(0);
  });

  it("offers no way back from a setting nobody made", () => {
    // The reset button is also the marker that a field is set. Showing it on an
    // untouched field would make every field look overridden.
    renderForm();
    expect(screen.queryByRole("button", { name: "Use provider default" })).not.toBeInTheDocument();
  });

  it("does not invent a value for a setting nobody touched", async () => {
    // The failure this whole shape exists for: an agent saved without opening
    // this card must save with no settings at all.
    // One keystroke: the form is controlled by its caller, and this one holds a
    // spy rather than state, so the field never fills up.
    const onChange = renderForm({});
    await userEvent.type(screen.getByLabelText("Max tokens"), "5");
    expect(onChange).toHaveBeenLastCalledWith({ max_tokens: 5 });
  });

  it("reports a moved slider as the number it moved to", () => {
    const onChange = renderForm();
    fireRange(temperature(), "0.3");
    expect(onChange).toHaveBeenCalledWith({ temperature: 0.3 });
  });

  it("shows a chosen temperature as a number and offers the way back", () => {
    renderForm({ temperature: 0.25 });
    expect(temperature()).toHaveValue("0.25");
    expect(screen.getByText("0.25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use provider default" })).toBeInTheDocument();
  });

  it("removes the key rather than storing null when a setting is given back", async () => {
    // `null` is a value, and a value is sent. Only an absent key is not.
    const onChange = renderForm({ temperature: 0.25, top_p: 0.9 });
    await userEvent.click(resetTemperature());
    expect(onChange).toHaveBeenLastCalledWith({ top_p: 0.9 });
    expect(onChange.mock.lastCall?.[0]).not.toHaveProperty("temperature");
  });

  it("keeps zero, which is the most deliberate temperature there is", () => {
    renderForm({ temperature: 0 });
    expect(screen.getByText("0.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use provider default" })).toBeInTheDocument();
  });

  it("clearing a number field unsets it rather than sending zero", async () => {
    const onChange = renderForm({ max_tokens: 512 });
    await userEvent.clear(screen.getByLabelText("Max tokens"));
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("leaves the other settings alone when one changes", () => {
    const onChange = renderForm({ max_tokens: 512 });
    fireRange(temperature(), "0.6");
    expect(onChange).toHaveBeenLastCalledWith({ max_tokens: 512, temperature: 0.6 });
  });

  it("keeps a slider inside the range the backend enforces", () => {
    // A value the backend refuses is a publish that fails for something the
    // control should not have allowed in the first place.
    renderForm();
    expect(temperature()).toHaveAttribute("max", "2");
    expect(screen.getByLabelText("Top P")).toHaveAttribute("max", "1");
    expect(screen.getByLabelText("Max tokens")).toHaveAttribute("max", "200000");
    expect(screen.getByLabelText("Timeout (seconds)")).toHaveAttribute("max", "600");
  });

  it("offers three answers for parallel tool calls, because there are three", () => {
    // Not a switch: "the provider decides" is the state an agent is in until
    // somebody says otherwise, and it is not a synonym for either answer.
    renderForm();
    expect(screen.getByRole("combobox", { name: "Tool calls" })).toHaveTextContent(
      PROVIDER_DEFAULT,
    );
  });

  it("shows a stored tool-call decision", () => {
    renderForm({ parallel_tool_calls: false });
    expect(screen.getByRole("combobox", { name: "Tool calls" })).toHaveTextContent("One at a time");
  });

  it("accepts nothing from a viewer who cannot edit", async () => {
    const onChange = renderForm({ temperature: 0.25 }, vi.fn(), true);
    await userEvent.click(resetTemperature());
    await userEvent.type(screen.getByLabelText("Max tokens"), "512");
    expect(onChange).not.toHaveBeenCalled();
  });
});

/**
 * Drag a range input to a value.
 *
 * `userEvent` has no gesture for one: a drag needs a track, and jsdom lays
 * nothing out, so every pointer gesture lands at the same place. `fireEvent`
 * sets the value the way the browser would and lets React see it.
 */
function fireRange(element: HTMLElement, value: string): void {
  fireEvent.change(element, { target: { value } });
}
