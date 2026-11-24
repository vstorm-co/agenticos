import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Dialog } from "@/components/ui";
import { RoutineDialogFrame } from "./routine-dialog-frame";

it("distinguishes a disabled consent draft from a pending write", () => {
  const view = render(
    <Dialog open>
      <RoutineDialogFrame title="Routine" description="Review the settings" disabled>
        <input aria-label="Routine name" />
      </RoutineDialogFrame>
    </Dialog>,
  );
  expect(screen.getByRole("group", { name: "Routine" })).toBeDisabled();
  expect(screen.getByLabelText("Routine name")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
  view.rerender(
    <Dialog open>
      <RoutineDialogFrame title="Routine" description="Review the settings" disabled pending>
        <input aria-label="Routine name" />
      </RoutineDialogFrame>
    </Dialog>,
  );
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
});
