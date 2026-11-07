import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";

import { InputContractForm } from "./input-contract-form";

const SCHEMA = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  type: "object",
  properties: { contacts: { type: "array", items: { $ref: "#/$defs/contact" } } },
  $defs: { contact: { type: "object", properties: { email: { type: "string", minLength: 1 } } } },
};

function node(config: Record<string, unknown> = {}, definition_id = "core.input"): NodeInstance {
  return { id: "start", definition_id, definition_version: 1, config, layout: { x: 0, y: 0 } };
}

function Live({ onUpdate }: { onUpdate: (id: string, config: Record<string, unknown>) => void }) {
  const [config, setConfig] = useState<Record<string, unknown>>({
    fields: [{ name: "email", type: "text" }],
  });
  return (
    <InputContractForm
      node={node(config)}
      updateNodeConfig={(id, next) => {
        onUpdate(id, next);
        setConfig(next);
      }}
    />
  );
}

describe("InputContractForm", () => {
  it("switches from simple fields to a portable schema and back", async () => {
    const update = vi.fn();
    render(<Live onUpdate={update} />);
    expect(screen.getByLabelText("Name")).toHaveValue("email");
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "JSON Schema" }));
    expect(update).toHaveBeenLastCalledWith("start", {
      fields: [],
      input_schema: {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
      },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "JSON Schema" }), {
      target: { value: JSON.stringify(SCHEMA) },
    });
    expect(update).toHaveBeenLastCalledWith("start", { fields: [], input_schema: SCHEMA });
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toHaveValue(
      JSON.stringify(SCHEMA),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "Simple fields" }));
    expect(update).toHaveBeenLastCalledWith("start", {
      fields: [{ name: "email", type: "text" }],
      input_schema: null,
    });
    expect(screen.getByLabelText("Name")).toHaveValue("email");
    expect(screen.getByRole("button", { name: "Add field" })).toBeVisible();
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "JSON Schema" }));
    expect(update).toHaveBeenLastCalledWith("start", { fields: [], input_schema: SCHEMA });
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toHaveValue(
      JSON.stringify(SCHEMA, null, 2),
    );
  });

  it("keeps changes to simple fields across format switches and sends one active contract", async () => {
    const update = vi.fn();
    render(<Live onUpdate={update} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "contact" } });
    const fields = update.mock.lastCall?.[1].fields;
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "JSON Schema" }));
    expect(update.mock.lastCall?.[1].fields).toEqual([]);
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "Simple fields" }));
    expect(update).toHaveBeenLastCalledWith("start", { fields, input_schema: null });
    expect(screen.getByLabelText("Name")).toHaveValue("contact");
  });

  it("discards an inactive format draft when an external restore changes the contract", async () => {
    const restored = { type: "object", properties: { restored: { type: "number" } } };
    function Restorable() {
      const [config, setConfig] = useState<Record<string, unknown>>({
        fields: [{ name: "email", type: "text" }],
      });
      return (
        <>
          <button onClick={() => setConfig({ fields: [], input_schema: restored })}>Restore</button>
          <InputContractForm
            node={node(config)}
            updateNodeConfig={(_id, next) => setConfig(next)}
          />
        </>
      );
    }
    render(<Restorable />);
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "JSON Schema" }));
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toHaveValue(
      JSON.stringify(restored, null, 2),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Input contract" }));
    await userEvent.click(screen.getByRole("option", { name: "Simple fields" }));
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("preserves the last saved contract while malformed JSON is being edited", () => {
    const update = vi.fn();
    render(
      <InputContractForm
        node={node({ input_schema: SCHEMA, retained: true })}
        updateNodeConfig={update}
      />,
    );
    const editor = screen.getByRole("textbox", { name: "JSON Schema" });
    expect(editor).toHaveValue(JSON.stringify(SCHEMA, null, 2));
    for (const value of ["{", "null", "[]", '"text"']) {
      fireEvent.change(editor, { target: { value } });
      expect(editor).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByText("Enter a JSON object. This edit was not saved.")).toBeVisible();
      expect(update).not.toHaveBeenCalled();
    }
    fireEvent.change(editor, { target: { value: "{}" } });
    expect(update).toHaveBeenLastCalledWith("start", {
      retained: true,
      fields: [],
      input_schema: {},
    });
    expect(
      screen.queryByText("Enter a JSON object. This edit was not saved."),
    ).not.toBeInTheDocument();
  });

  it("keeps public forms on their existing simple fields", () => {
    render(<InputContractForm node={node({}, "trigger.form")} updateNodeConfig={vi.fn()} />);
    expect(screen.queryByRole("combobox", { name: "Input contract" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add field" })).toBeVisible();
  });

  it("updates the editor when a version restore or undo changes the same trigger", () => {
    const update = vi.fn();
    const { rerender } = render(
      <InputContractForm node={node({ input_schema: SCHEMA })} updateNodeConfig={update} />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "JSON Schema" }), {
      target: { value: "{" },
    });
    const restored = { type: "object", properties: { changed: { type: "boolean" } } };
    rerender(
      <InputContractForm node={node({ input_schema: restored })} updateNodeConfig={update} />,
    );
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toHaveValue(
      JSON.stringify(restored, null, 2),
    );
    expect(
      screen.queryByText("Enter a JSON object. This edit was not saved."),
    ).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("disables the contract controls when the workflow is read only", () => {
    render(
      <InputContractForm
        node={node({ input_schema: SCHEMA })}
        disabled
        updateNodeConfig={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Input contract" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toBeDisabled();
  });
});
