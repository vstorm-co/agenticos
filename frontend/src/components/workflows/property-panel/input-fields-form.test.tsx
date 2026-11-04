import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";

import { InputFieldsForm } from "./input-fields-form";

function node(config: Record<string, unknown> = {}): NodeInstance {
  return {
    id: "n1",
    definition_id: "core.input",
    definition_version: 1,
    config,
    layout: { x: 0, y: 0 },
  };
}

/** The form over a node whose config follows each edit, as the editor's store does. */
function Live({
  initial,
  onUpdate,
}: {
  initial: Record<string, unknown>;
  onUpdate: (id: string, config: Record<string, unknown>) => void;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <InputFieldsForm
      node={node(config)}
      updateNodeConfig={(id, next) => {
        onUpdate(id, next);
        setConfig(next);
      }}
    />
  );
}

const EMAIL = {
  name: "email",
  label: null,
  type: "text",
  required: true,
  description: null,
  options: [],
};

describe("InputFieldsForm", () => {
  it("says a trigger with no fields takes any object, and adds one under a free name", async () => {
    const update = vi.fn();
    render(
      <InputFieldsForm
        node={node({ fields: [{ ...EMAIL, name: "field_2" }] })}
        updateNodeConfig={update}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    expect(update).toHaveBeenCalledWith("n1", {
      fields: [
        { ...EMAIL, name: "field_2" },
        { ...EMAIL, name: "field_3" },
      ],
    });

    render(<InputFieldsForm node={node()} updateNodeConfig={update} />);
    expect(screen.getByText(/a run takes any JSON object/)).toBeTruthy();
  });

  it("writes each edit into the node's config as it is typed", async () => {
    const update = vi.fn();
    render(<Live initial={{ fields: [EMAIL] }} onUpdate={update} />);
    expect(screen.getByText("payload.email")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Label of email"), { target: { value: "Email" } });
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [{ ...EMAIL, label: "Email" }] });
    fireEvent.change(screen.getByLabelText("Label of email"), { target: { value: "" } });
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [EMAIL] });

    fireEvent.change(screen.getByLabelText("Description of email"), {
      target: { value: "Who to write to" },
    });
    expect(update).toHaveBeenLastCalledWith("n1", {
      fields: [{ ...EMAIL, description: "Who to write to" }],
    });
    fireEvent.change(screen.getByLabelText("Description of email"), { target: { value: "" } });
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [EMAIL] });

    await userEvent.click(screen.getByRole("checkbox"));
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [{ ...EMAIL, required: false }] });
    await userEvent.click(screen.getByRole("checkbox"));

    await userEvent.click(screen.getByRole("combobox", { name: "Type" }));
    await userEvent.click(screen.getByRole("option", { name: "Choice" }));
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [{ ...EMAIL, type: "choice" }] });

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "mail" } });
    expect(update).toHaveBeenLastCalledWith("n1", {
      fields: [{ ...EMAIL, name: "mail", type: "choice" }],
    });

    await userEvent.click(screen.getByRole("button", { name: "Remove mail" }));
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [] });
  });

  it("marks a name that cannot be published, and a choice with no options", () => {
    const update = vi.fn();
    const choice = { ...EMAIL, name: "plan", type: "choice", options: [] };
    render(
      <InputFieldsForm
        node={node({ fields: [EMAIL, { ...EMAIL }, { ...EMAIL, name: "Bad name" }, choice] })}
        updateNodeConfig={update}
      />,
    );
    expect(screen.getByText("Another field already has this name.")).toBeTruthy();
    expect(screen.getByText(/Lower-case letters, digits and underscores/)).toBeTruthy();
    expect(screen.getByText("A choice needs at least one option.")).toBeTruthy();
  });

  it("reads a choice's options one per line, and says when there are too many", () => {
    const update = vi.fn();
    const many = Array.from({ length: 51 }, (_, i) => `o${i}`);
    render(
      <InputFieldsForm
        node={node({ fields: [{ ...EMAIL, type: "choice", options: many }] })}
        updateNodeConfig={update}
      />,
    );
    expect(screen.getByText("A choice offers at most 50 options.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Options of email"), {
      target: { value: "basic\n\n pro \n" },
    });
    expect(update).toHaveBeenLastCalledWith("n1", {
      fields: [{ ...EMAIL, type: "choice", options: ["basic", "pro"] }],
    });
  });

  it("switching a choice to another type drops its options", async () => {
    const update = vi.fn();
    render(
      <InputFieldsForm
        node={node({ fields: [{ ...EMAIL, type: "choice", options: ["a"] }] })}
        updateNodeConfig={update}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Type" }));
    await userEvent.click(screen.getByRole("option", { name: "Date" }));
    expect(update).toHaveBeenLastCalledWith("n1", { fields: [{ ...EMAIL, type: "date" }] });
  });
});
