import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { EvalTarget } from "./eval-target";
import { TargetChoice } from "./start-eval-fields";

function Choice({ draftDiffers = true }: { draftDiffers?: boolean }) {
  const [value, setValue] = useState<EvalTarget>("version");
  return (
    <TargetChoice
      targets={["compare", "version", "draft"]}
      value={value}
      onChange={setValue}
      currentVersion={7}
      draftDiffers={draftDiffers}
    />
  );
}

it("allows keyboard selection across evaluation targets", async () => {
  render(<Choice />);
  await userEvent.tab();
  expect(screen.getByRole("radio", { name: /v7 alone/ })).toHaveFocus();
  await userEvent.keyboard("{ArrowLeft}");
  expect(screen.getByRole("radio", { name: /The draft against v7/ })).toBeChecked();
  await userEvent.keyboard("{ArrowRight}{ArrowRight}");
  expect(screen.getByRole("radio", { name: /^The draft Nothing/ })).toBeChecked();
});

it("skips unavailable comparisons when navigating by keyboard", async () => {
  render(<Choice draftDiffers={false} />);
  expect(screen.getByRole("radio", { name: /No changes/ })).toBeDisabled();
  await userEvent.tab();
  await userEvent.keyboard("{ArrowLeft}");
  expect(screen.getByRole("radio", { name: /^The draft Nothing/ })).toBeChecked();
});
