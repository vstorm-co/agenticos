import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ModelPickerPreview, type PreviewModel } from "./model-picker-preview";

const models: PreviewModel[] = [
  {
    id: "one",
    model: "anthropic/claude",
    name: "Claude",
    provider: "openrouter",
    maker: "Anthropic",
    saved: true,
  },
  {
    id: "two",
    model: "openai/gpt",
    name: "GPT",
    provider: "openrouter",
    maker: "OpenAI",
    saved: false,
  },
];
it.each(["list", "library", "command"] as const)(
  "searches and selects locally in %s",
  async (variant) => {
    render(<ModelPickerPreview variant={variant} models={models} />);
    await userEvent.type(screen.getByRole("combobox"), "GPT");
    expect(screen.queryByRole("option", { name: /Claude/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /GPT/ }));
    expect(
      within(screen.getByRole("option", { name: /GPT/ })).getByLabelText("Selected"),
    ).toBeInTheDocument();
    expect(screen.getByText("Preview only")).toBeVisible();
  },
);
it("filters the library by maker and restores all makers", async () => {
  render(<ModelPickerPreview variant="library" models={models} />);
  await userEvent.click(screen.getByRole("button", { name: "OpenAI" }));
  expect(screen.queryByRole("option", { name: /Claude/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "All makers" }));
  expect(screen.getAllByRole("option")).toHaveLength(2);
});
