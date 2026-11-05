import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MirageOptions } from "./mirage-options";
import type { JsonSchema } from "@/types/agents";

const schema: JsonSchema = {
  properties: {
    timeout: { type: "number", title: "Timeout" },
    elide_fields: { type: "object", title: "Elide fields", default: {} },
  },
};

function editor(field = "Elide fields") {
  return screen.getByLabelText(`${field} (JSON)`);
}

describe("Mirage structured options", () => {
  it("preserves a mapping while another setting changes and commits edits as objects", () => {
    const changed = vi.fn();
    function Form() {
      const [value, setValue] = useState<Record<string, unknown>>({
        timeout: 12,
        elide_fields: { customers: ["ssn"] },
      });
      return (
        <MirageOptions
          schema={schema}
          value={value}
          onChange={(next) => {
            setValue(next);
            changed(next);
          }}
          idPrefix="options"
        />
      );
    }
    render(<Form />);
    expect(editor()).toHaveValue(JSON.stringify({ customers: ["ssn"] }, null, 2));
    fireEvent.change(screen.getByLabelText("Timeout"), { target: { value: "15" } });
    expect(changed).toHaveBeenLastCalledWith({ timeout: 15, elide_fields: { customers: ["ssn"] } });
    fireEvent.change(editor(), { target: { value: '{"customers":["email"]}' } });
    expect(changed).toHaveBeenLastCalledWith({
      timeout: 15,
      elide_fields: { customers: ["email"] },
    });
    expect(editor()).toHaveValue('{"customers":["email"]}');
  });

  it.each(["{", "[]", "null", '"wrong"', "3"])(
    "keeps the stored mapping for an invalid draft: %s",
    (draft) => {
      const changed = vi.fn();
      render(
        <MirageOptions
          schema={schema}
          value={{ elide_fields: { customers: ["ssn"] } }}
          onChange={changed}
          idPrefix="options"
        />,
      );
      fireEvent.change(editor(), { target: { value: draft } });
      expect(changed).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent("last valid value");
      expect(editor()).toHaveAttribute("aria-invalid", "true");
    },
  );

  it("clears an optional mapping without dropping neighboring settings", () => {
    const changed = vi.fn();
    render(
      <MirageOptions
        schema={schema}
        value={{ timeout: 15, elide_fields: {} }}
        onChange={changed}
        idPrefix="options"
      />,
    );
    fireEvent.change(editor(), { target: { value: "" } });
    expect(changed).toHaveBeenLastCalledWith({ timeout: 15 });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps a required mapping when it is cleared", () => {
    const changed = vi.fn();
    render(
      <MirageOptions
        schema={{ ...schema, required: ["elide_fields"] }}
        value={{ elide_fields: {} }}
        onChange={changed}
        idPrefix="options"
      />,
    );
    fireEvent.change(editor(), { target: { value: " " } });
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it.each([
    { type: "array", items: { type: "number" } },
    { anyOf: [{ type: "null" }, { type: "array", items: { type: "number" } }] },
  ])("edits a structured array rather than a string", (property) => {
    const changed = vi.fn();
    render(
      <MirageOptions
        schema={{ properties: { limits: property } }}
        value={{}}
        onChange={changed}
        idPrefix="options"
      />,
    );
    expect(editor("limits")).toHaveValue("[]");
    fireEvent.change(editor("limits"), { target: { value: "[1,2]" } });
    expect(changed).toHaveBeenLastCalledWith({ limits: [1, 2] });
    fireEvent.change(editor("limits"), { target: { value: "{}" } });
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it.each([{ type: ["object", "null"] }, { anyOf: [{ type: "null" }, { type: "object" }] }])(
    "honors nullable structured fields",
    (property) => {
      const changed = vi.fn();
      render(
        <MirageOptions
          schema={{ properties: { mapping: property } }}
          value={{ mapping: {} }}
          onChange={changed}
          idPrefix="options"
        />,
      );
      fireEvent.change(editor("mapping"), { target: { value: "null" } });
      expect(changed).toHaveBeenCalledWith({ mapping: null });
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );

  it("keeps string lists in the regular form", () => {
    render(
      <MirageOptions
        schema={{
          properties: {
            tags: { anyOf: [{ type: "null" }, { type: "array", items: { type: "string" } }] },
          },
        }}
        value={{ tags: ["one"] }}
        onChange={vi.fn()}
        idPrefix="options"
      />,
    );
    expect(screen.queryByLabelText("tags (JSON)")).toBeNull();
  });

  it("updates an open editor when the saved record changes externally", () => {
    const changed = vi.fn();
    const view = render(
      <MirageOptions
        schema={schema}
        value={{ elide_fields: {} }}
        onChange={changed}
        idPrefix="options"
      />,
    );
    fireEvent.change(editor(), { target: { value: "{" } });
    view.rerender(
      <MirageOptions
        schema={schema}
        value={{ elide_fields: { orders: ["secret"] } }}
        onChange={changed}
        idPrefix="options"
        disabled
      />,
    );
    expect(editor()).toHaveValue(JSON.stringify({ orders: ["secret"] }, null, 2));
    expect(editor()).toHaveAttribute("readonly");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a backend's description and handles an empty schema", () => {
    const view = render(
      <MirageOptions
        schema={{
          properties: {
            mapping: { type: "object", description: "Fields omitted from each collection." },
          },
        }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="options"
      />,
    );
    expect(screen.getByText("Fields omitted from each collection.")).toBeInTheDocument();
    expect(editor("mapping")).toHaveValue("{}");
    view.rerender(<MirageOptions schema={{}} value={{}} onChange={vi.fn()} idPrefix="options" />);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

it("preserves a backend's explicit null default", () => {
  render(
    <MirageOptions
      schema={{
        properties: { mapping: { anyOf: [{ type: "object" }, { type: "null" }], default: null } },
      }}
      value={{}}
      onChange={vi.fn()}
      idPrefix="options"
    />,
  );
  expect(editor("mapping")).toHaveValue("null");
});
