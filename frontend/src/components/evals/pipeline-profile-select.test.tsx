import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ModelProfile } from "@/types/providers";
import { PipelineProfileSelect } from "./pipeline-profile-select";

const support: ModelProfile = {
  id: "support",
  label: "Support",
  provider: "anthropic",
  model: "claude-sonnet-4-6",
  secret_id: "key",
  params: {},
  fallback_profile_ids: [],
};
const fast: ModelProfile = {
  ...support,
  id: "fast",
  label: "Fast",
  provider: "openai",
  model: "gpt-5.5",
};
const embedding: ModelProfile = {
  ...support,
  id: "embedding",
  label: "Embedding",
  chat_capable: false,
};
const missing: ModelProfile = {
  ...support,
  id: "missing",
  label: "Missing key",
  missing_key: true,
};

describe("saved pipeline model selection", () => {
  it("searches the provider or model and selects with the keyboard", async () => {
    const onChange = vi.fn();
    render(
      <PipelineProfileSelect
        profiles={[support, fast, embedding, missing]}
        value={null}
        onChange={onChange}
      />,
    );
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    expect(screen.queryByRole("option", { name: /Embedding/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Missing key/ })).toBeNull();
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "gpt-5.5");
    expect(screen.queryByRole("option", { name: /Support/ })).toBeNull();
    expect(screen.getByRole("option", { name: /Fast/ })).toBeVisible();
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("fast");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("keeps an unusable stored selection visible and explains the missing key", async () => {
    render(
      <PipelineProfileSelect profiles={[support, missing]} value="missing" onChange={vi.fn()} />,
    );
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent("Missing key");
    expect(screen.getByRole("alert")).toHaveTextContent(/key/);
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    expect(screen.getByRole("option", { name: /Missing key/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("prevents selection in a read-only form", async () => {
    const onChange = vi.fn();
    render(
      <PipelineProfileSelect profiles={[support]} value="support" onChange={onChange} disabled />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});

it("explains a stored non-chat model and lets search find a replacement", async () => {
  render(
    <PipelineProfileSelect profiles={[embedding, support]} value="embedding" onChange={vi.fn()} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(/not a chat model/);
  await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
  expect(screen.getByRole("option", { name: /Embedding/ })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await userEvent.type(screen.getByPlaceholderText("Search models…"), "no-such-model");
  expect(screen.getByText("No matching models")).toBeVisible();
});

it("keeps a selected profile readable without repeating its technical name", async () => {
  const profile = { ...support, label: "anthropic · claude-sonnet-4-6" };
  render(<PipelineProfileSelect profiles={[profile]} value={profile.id} onChange={vi.fn()} />);
  expect(screen.queryByRole("alert")).toBeNull();
  await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
  expect(screen.getByRole("option", { name: profile.label })).toBeVisible();
});
