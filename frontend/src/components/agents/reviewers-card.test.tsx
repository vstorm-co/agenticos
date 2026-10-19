import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ReviewersCard } from "./reviewers-card";
import type { RunReviewerSpec } from "@/types/agents";

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: [{ id: "haiku", label: "Claude Haiku" }],
    profilesStatus: "ready",
  }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({ onChange }: { onChange: (id: string | null) => void }) => (
    <button type="button" onClick={() => onChange(null)}>
      pick-model
    </button>
  ),
}));

const SOURCES: RunReviewerSpec = {
  name: "sources",
  model_profile_id: "haiku",
  instructions: "Flag claims without a source.",
  every: 10,
  window: 20000,
};

function show(value: RunReviewerSpec[] | undefined, onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ReviewersCard value={value} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("ReviewersCard", () => {
  it("adds a reviewer on the organization's first model, with the spec's defaults", async () => {
    const onChange = show(undefined);
    await userEvent.click(screen.getByRole("button", { name: "Add a reviewer" }));
    expect(onChange).toHaveBeenCalledWith([
      {
        name: "reviewer-1",
        model_profile_id: "haiku",
        instructions: "",
        every: 10,
        window: 20000,
      },
    ]);
  });

  it("edits each field of a reviewer, and removes one", async () => {
    const onChange = show([SOURCES]);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "scope" } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...SOURCES, name: "scope" }]);
    fireEvent.change(screen.getByLabelText("What to look for"), {
      target: { value: "Stay on task." },
    });
    expect(onChange).toHaveBeenLastCalledWith([{ ...SOURCES, instructions: "Stay on task." }]);
    fireEvent.change(screen.getByLabelText("Every N requests"), { target: { value: "5" } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...SOURCES, every: 5 }]);
    fireEvent.change(screen.getByLabelText("Tokens it reads"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...SOURCES, window: 1000 }]);
    await userEvent.click(screen.getByText("pick-model"));
    expect(onChange).toHaveBeenLastCalledWith([{ ...SOURCES, model_profile_id: null }]);
    await userEvent.click(screen.getByRole("button", { name: "Remove reviewer sources" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("names a new reviewer after the first number nobody has", async () => {
    const onChange = show([
      { ...SOURCES, name: "reviewer-2" },
      { ...SOURCES, name: "reviewer-1" },
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Add a reviewer" }));
    expect(onChange.mock.calls[0]![0][2].name).toBe("reviewer-3");
  });

  it("offers no more than the spec allows", () => {
    show(Array.from({ length: 5 }, (_, n) => ({ ...SOURCES, name: `r${n}` })));
    expect(screen.queryByRole("button", { name: "Add a reviewer" })).toBeNull();
  });
});
