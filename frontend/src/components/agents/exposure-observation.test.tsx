import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ExposureObservation } from "./exposure-observation";

vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({ onChange }: { onChange: (id: string) => void }) => (
    <button type="button" onClick={() => onChange("small-model")}>
      Choose small model
    </button>
  ),
}));

async function mount(onSave = vi.fn().mockResolvedValue(undefined)) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ExposureObservation disabled={false} onSave={onSave} />
    </NextIntlClientProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Configure" }));
  return onSave;
}

describe("automatic channel participation", () => {
  it("starts off with separate 20 and 1 minute intervals", async () => {
    await mount();
    const dialog = within(screen.getByRole("dialog"));
    expect(
      dialog.getByRole("switch", { name: "Enable automatic participation" }),
    ).not.toBeChecked();
    expect(dialog.getByRole("spinbutton", { name: "Before the agent is mentioned" })).toHaveValue(
      20,
    );
    expect(dialog.getByRole("spinbutton", { name: "After the agent is mentioned" })).toHaveValue(1);
  });

  it("requires an explicit model before enabling", async () => {
    const save = await mount();
    await userEvent.click(screen.getByRole("switch", { name: "Enable automatic participation" }));
    await userEvent.click(screen.getByRole("button", { name: "Save participation settings" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Select the model");
    expect(save).not.toHaveBeenCalled();
  });

  it("saves the selected model, focus and cadence together", async () => {
    const save = await mount();
    await userEvent.click(screen.getByRole("switch", { name: "Enable automatic participation" }));
    await userEvent.click(screen.getByRole("button", { name: "Choose small model" }));
    await userEvent.type(
      screen.getByLabelText("What to focus on and when to contribute"),
      "Help with unanswered product questions",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save participation settings" }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        model_profile_id: "small-model",
        instructions: "Help with unanswered product questions",
        unmentioned_interval_minutes: 20,
        mentioned_interval_minutes: 1,
      }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the edited form open when saving fails", async () => {
    await mount(vi.fn().mockRejectedValue(new Error("Offline")));
    await userEvent.type(
      screen.getByLabelText("What to focus on and when to contribute"),
      "Keep my edits",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save participation settings" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save");
    expect(screen.getByLabelText("What to focus on and when to contribute")).toHaveValue(
      "Keep my edits",
    );
  });
});
