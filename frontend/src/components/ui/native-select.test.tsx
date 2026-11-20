import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { FormField } from "./form-field";
import { NativeSelect } from "./native-select";

it("keeps native selection, accessible validation and the forwarded ref", async () => {
  const change = vi.fn();
  const ref = createRef<HTMLSelectElement>();
  render(
    <FormField label="Workspace" htmlFor="workspace" error="Choose a workspace">
      <NativeSelect ref={ref} defaultValue="one" onChange={change}>
        <option value="one">First workspace</option>
        <option value="two">Second workspace</option>
      </NativeSelect>
    </FormField>,
  );
  const control = screen.getByRole("combobox", { name: "Workspace" });
  expect(ref.current).toBe(control);
  expect(control).toHaveAttribute("aria-invalid", "true");
  expect(control).toHaveAccessibleDescription("Choose a workspace");
  await userEvent.selectOptions(control, "two");
  expect(control).toHaveValue("two");
  expect(change).toHaveBeenCalledOnce();
});

it("prevents changing a disabled select", async () => {
  const change = vi.fn();
  render(
    <NativeSelect aria-label="Workspace" disabled defaultValue="one" onChange={change}>
      <option value="one">First workspace</option>
      <option value="two">Second workspace</option>
    </NativeSelect>,
  );
  await userEvent.selectOptions(screen.getByRole("combobox"), "two");
  expect(screen.getByRole("combobox")).toHaveValue("one");
  expect(change).not.toHaveBeenCalled();
});
