import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelCombobox, type ModelOption } from "./model-combobox";

const OPTIONS: ModelOption[] = [
  { id: "anthropic/claude-opus-5", name: "Claude Opus 5", context_length: 1_000_000 },
  { id: "openai/gpt-5.6-sol", name: "GPT-5.6 Sol", context_length: 1_050_000 },
  { id: "google/gemini-3.6-flash", name: "Gemini 3.6 Flash", context_length: 1_048_576 },
];

function mount(props: Partial<Parameters<typeof ModelCombobox>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <ModelCombobox
      value=""
      onChange={onChange}
      options={OPTIONS}
      source="live"
      placeholder="Pick a provider first"
      {...props}
    />,
  );
  return { onChange };
}

describe("the model combobox", () => {
  it("shows the catalog as a list, not as a hint that appears once you guess a prefix", async () => {
    // The regression this replaces: the field was a text input with a
    // `<datalist>`, which browsers surface only after a matching prefix is
    // typed. Six hundred known models looked exactly like none.
    mount();

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getByText("anthropic/claude-opus-5")).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-5.6-sol")).toBeInTheDocument();
  });

  it("finds a model by its name, not only by its id", async () => {
    // "opus" is the name and "claude-opus" is the id; people search with either.
    mount();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "Gemini");

    expect(screen.getByText("google/gemini-3.6-flash")).toBeInTheDocument();
    expect(screen.queryByText("openai/gpt-5.6-sol")).toBeNull();
  });

  it("accepts a model that is not in the list", async () => {
    // The whole reason the field was free text: a provider ships a model the
    // morning after the catalog was warmed, and a picker that cannot express
    // "that one" is one people work around by editing the spec by hand.
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "openai/gpt-6");
    await userEvent.click(screen.getByText("not in the list"));

    expect(onChange).toHaveBeenCalledWith("openai/gpt-6");
  });

  it("does not offer a typed id back when the list already has it", async () => {
    // Otherwise the exact match appears twice, once as itself and once as a
    // "not in the list" escape hatch that is a lie.
    mount();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "anthropic/claude-opus-5");

    expect(screen.queryByText("not in the list")).toBeNull();
  });

  it("says when the list is this deployment's shortlist rather than the provider's", async () => {
    // A curated list is a stale list, and somebody choosing from it should know
    // that the id they want may simply not be in it.
    mount({ source: "curated" });

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getByText(/deployment's own shortlist/)).toBeInTheDocument();
  });

  it("reads a context window in the unit a person uses", async () => {
    mount({ value: "anthropic/claude-opus-5" });

    expect(screen.getByText("1M ctx")).toBeInTheDocument();
  });

  it("reads a small context window in thousands, and a fractional one to one place", async () => {
    // `1048576` is not a number anybody reads, and neither is `1.048576M`.
    mount({ options: [{ id: "m", name: "M", context_length: 8_192 }], value: "m" });
    expect(screen.getByText("8K ctx")).toBeInTheDocument();
  });

  it("reads a context window smaller than a thousand as itself", () => {
    mount({ options: [{ id: "m", name: "M", context_length: 512 }], value: "m" });
    expect(screen.getByText("512 ctx")).toBeInTheDocument();
  });

  it("says nothing about a context window the provider did not publish", () => {
    // Zero and null both mean "unknown" here; printing "0 ctx" would read as a
    // model that can hold nothing.
    mount({ options: [{ id: "m", name: "M", context_length: 0 }], value: "m" });
    expect(screen.queryByText(/ctx/)).toBeNull();
  });

  it("says a provider publishes no list rather than showing an empty dropdown", async () => {
    mount({ options: [], source: "live" });

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getByText(/publishes no list here/)).toBeInTheDocument();
  });

  it("says the catalog is still being read", async () => {
    mount({ options: [], loading: true });

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getByText("Reading the catalog…")).toBeInTheDocument();
  });

  it("hands back the id of the model that was picked", async () => {
    // The name is what somebody searched on; the id is what the spec stores.
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByText("Claude Opus 5"));

    expect(onChange).toHaveBeenCalledWith("anthropic/claude-opus-5");
  });
});
