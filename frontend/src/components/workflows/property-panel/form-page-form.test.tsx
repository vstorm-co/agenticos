import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";

import { FormPageForm } from "./form-page-form";

const node = (config: Record<string, unknown>) =>
  ({ id: "n1", definition_id: "trigger.form", config }) as unknown as NodeInstance;

describe("FormPageForm", () => {
  it("shows the page's words and writes an edit into the config", () => {
    const update = vi.fn();
    render(
      <FormPageForm node={node({ title: "Talk to us", fields: [] })} updateNodeConfig={update} />,
    );

    expect(screen.getByLabelText("Title")).toHaveValue("Talk to us");
    expect(screen.getByLabelText("Button")).toHaveAttribute("placeholder", "Submit");
    fireEvent.change(screen.getByLabelText("After sending"), { target: { value: "Thanks!" } });

    expect(update).toHaveBeenCalledWith("n1", {
      title: "Talk to us",
      fields: [],
      success_message: "Thanks!",
    });
  });

  it("takes a box left empty out of the config, so the default wording returns", () => {
    const update = vi.fn();
    render(
      <FormPageForm node={node({ title: "Talk to us", fields: [] })} updateNodeConfig={update} />,
    );

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "" } });

    expect(update).toHaveBeenCalledWith("n1", { fields: [] });
  });
});
