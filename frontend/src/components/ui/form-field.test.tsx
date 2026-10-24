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
});
