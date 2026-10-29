import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { diffLine } from "@/test-utils/diff";
import { InstructionsEditor, editedPassage } from "./instructions-editor";

const wide = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/use-wide-screen", () => ({ useWideScreen: () => wide.value }));

const CURRENT = "You answer refunds.\nRefunds take 30 days.\nBe brief.";

function Editor({ outside = false }: { outside?: boolean }) {
  const [value, setValue] = useState(CURRENT.replace("30 days", "14 days"));
  return (
    <InstructionsEditor current={CURRENT} value={value} outside={outside} onChange={setValue} />
  );
}

beforeEach(() => {
  wide.value = false;
});

it("comes to the passage between the parts that stay as they are, or to nothing", () => {
  expect(editedPassage("Intro. Mine. Outro.", "Intro. ", " Outro.")).toBe("Mine.");
  expect(editedPassage("Intro. Outro.", "Intro. ", "Outro.")).toBe("");
  expect(editedPassage("Changed intro. Mine. Outro.", "Intro. ", " Outro.")).toBeNull();
  expect(editedPassage("Intro. Mine. Changed", "Intro. ", " Outro.")).toBeNull();
  expect(editedPassage("short", "Intro. ", " Outro.")).toBeNull();
});

it("puts the current and the editable proposed instructions side by side on a wide screen", async () => {
  wide.value = true;
  render(<Editor />);
  expect(screen.getByLabelText("Current instructions")).toHaveTextContent("Refunds take 30 days.");
  const proposed = screen.getByRole("textbox", { name: "Proposed instructions, editable" });
  expect(screen.getByText(diffLine("Refunds take 14 days."))).toBeInTheDocument();
  await userEvent.clear(proposed);
  await userEvent.type(proposed, "Refunds take 7 days.");
  expect(screen.getByText(diffLine("Refunds take 7 days."))).toBeInTheDocument();
  expect(screen.queryByRole("tablist")).toBeNull();
});

it("shows the two versions as tabs on a phone, and warns about an edit outside the passage", async () => {
  render(<Editor outside />);
  expect(screen.getByRole("tab", { name: "Proposed (edit)" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.queryByLabelText("Current instructions")).toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: "Current instructions" }));
  expect(screen.getByLabelText("Current instructions")).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.getByRole("alert")).toHaveTextContent(/outside the suggested passage/);
});
