import userEvent from "@testing-library/user-event";
import { Switch } from "./switch";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FormField } from "./form-field";
import { Input } from "./input";

describe("FormField feedback", () => {
  it("describes an invalid field with its error and preserves external help", () => {
    render(
      <>
        <p id="policy">Names must be unique.</p>
        <FormField htmlFor="name" label="Name" description="Choose a name." error="Already exists.">
          <Input aria-describedby="policy" />
        </FormField>
      </>,
    );
    const field = screen.getByRole("textbox", { name: "Name" });
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("Names must be unique. Already exists.");
    expect(field).toHaveAttribute("aria-describedby", "policy name-err");
    expect(screen.getByRole("alert")).toHaveTextContent("Already exists.");
    expect(screen.queryByText("Choose a name.")).not.toBeInTheDocument();
  });

  it("keeps a switch labelled and described when its control sits beside the text", async () => {
    render(
      <FormField
        layout="switch"
        htmlFor="reminders"
        label="Allow reminders"
        description="Only for conversations you follow."
      >
        <Switch />
      </FormField>,
    );
    const toggle = screen.getByRole("switch", { name: "Allow reminders" });
    expect(toggle).toHaveAccessibleDescription("Only for conversations you follow.");
    expect(toggle).not.toBeChecked();
    await userEvent.click(screen.getByText("Allow reminders"));
    expect(toggle).toBeChecked();
  });

  it("returns to helper text when a validation error is resolved", () => {
    const { rerender } = render(
      <FormField htmlFor="name" label="Name" error="Required.">
        <Input />
      </FormField>,
    );
    rerender(
      <FormField htmlFor="name" label="Name" description="Choose a unique name.">
        <Input />
      </FormField>,
    );
    expect(screen.getByRole("textbox")).toHaveAccessibleDescription("Choose a unique name.");
    expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("associates its label with an explicitly named control and exposes required", () => {
    render(
      <FormField htmlFor="account" label="Account" required>
        <Input id="account-email" />
      </FormField>,
    );
    expect(screen.getByRole("textbox", { name: "Account" })).toHaveAttribute("id", "account-email");
    expect(screen.getByRole("textbox", { name: "Account" })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });
});

it("offers optional help on demand while retaining the field's accessible description", async () => {
  render(
    <FormField htmlFor="project" label="Project" help="Choose where the files belong.">
      <Input />
    </FormField>,
  );
  const input = screen.getByRole("textbox", { name: "Project" });
  expect(input).toHaveAccessibleDescription("Choose where the files belong.");
  await userEvent.click(screen.getByRole("button", { name: "More information" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Choose where the files belong.");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps requirements and validation visible when optional help is provided", () => {
  const { rerender } = render(
    <FormField htmlFor="limit" label="Limit" description="At least 1" help="How limits work">
      <Input />
    </FormField>,
  );
  expect(screen.getByText("At least 1")).toBeVisible();
  expect(screen.getByRole("textbox")).toHaveAccessibleDescription("At least 1");
  rerender(
    <FormField htmlFor="limit" help="How limits work" error="Too small">
      <Input aria-label="Limit" />
    </FormField>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Too small");
  expect(screen.getByRole("textbox")).toHaveAccessibleDescription("Too small");
  expect(screen.getByRole("button", { name: "More information" })).toBeVisible();
});
