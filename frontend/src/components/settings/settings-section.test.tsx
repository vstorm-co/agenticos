import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { SectionCard, SettingsSection } from "./settings-section";

it("keeps destructive-action warnings visible before any help is opened", () => {
  render(
    <SettingsSection
      title="Delete account"
      description="This permanently removes your data."
      danger
    >
      <button>Delete</button>
    </SettingsSection>,
  );
  expect(screen.getByText("This permanently removes your data.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "More information" })).not.toBeInTheDocument();
});

it.each([SectionCard, SettingsSection])(
  "offers secondary guidance without hiding fields",
  async (Section) => {
    render(
      <Section title="Preferences" description="How these settings work">
        <label>
          Required name
          <input required />
        </label>
      </Section>,
    );
    expect(screen.getByLabelText("Required name")).toBeVisible();
    expect(screen.queryByText("How these settings work")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More information" }));
    expect(await screen.findByText("How these settings work")).toBeVisible();
  },
);
