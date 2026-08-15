import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SchemaForm } from "./schema-form";
import type { JsonSchema } from "@/types/agents";

const SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    default_top_k: {
      type: "integer",
      description: "Passages returned when the model does not ask for a number",
      default: 5,
      minimum: 1,
      maximum: 50,
    },
    tool_name: {
      // Pydantic renders an optional field this way, not as a plain type.
      anyOf: [{ type: "string" }, { type: "null" }],
      title: "Tool name",
      description: "Rename the search tool for the model",
      maxLength: 64,
    },
    verbose: { type: "boolean", default: false },
    effort: {
      // How Pydantic renders `Literal[...] | None` - the values live on a
      // branch, not on the property.
      anyOf: [{ type: "string", enum: ["low", "medium", "high"] }, { type: "null" }],
      title: "Effort",
      description: "How hard the model reasons before answering",
    },
  },
  required: ["default_top_k"],
};

function renderForm(value: Record<string, unknown> = {}, onChange = vi.fn()) {
  render(<SchemaForm schema={SCHEMA} value={value} onChange={onChange} idPrefix="knowledge" />);
  return onChange;
}

describe("SchemaForm", () => {
  it("renders nothing when a capability has nothing to configure", () => {
    const { container } = render(
      <SchemaForm schema={{ type: "object" }} value={{}} onChange={vi.fn()} idPrefix="x" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("uses the schema title when there is one", () => {
    renderForm();
    expect(screen.getByLabelText(/Tool name/)).toBeInTheDocument();
  });

  it("humanises a field name when the schema has no title", () => {
    renderForm();
    expect(screen.getByLabelText(/Default top k/)).toBeInTheDocument();
  });

  it("marks required fields", () => {
    renderForm();
    expect(screen.getByLabelText(/Default top k \*/)).toBeInTheDocument();
  });

  it("shows the description, which is the only guidance a builder gets", () => {
    renderForm();
    expect(
      screen.getByText("Passages returned when the model does not ask for a number"),
    ).toBeInTheDocument();
  });

  it("renders an optional string as a text input rather than falling through", () => {
    // Pydantic's anyOf: [string, null] is the shape every optional field takes.
    // Reading past the null branch is what keeps them from all becoming text
    // boxes by accident - and this one genuinely is a text box, so assert the
    // number field is what proves the branch works.
    renderForm();
    expect(screen.getByLabelText(/Default top k/)).toHaveAttribute("type", "number");
    expect(screen.getByLabelText(/Tool name/)).not.toHaveAttribute("type", "number");
  });

  it("carries the schema's bounds onto the input", () => {
    renderForm();
    const field = screen.getByLabelText(/Default top k/);
    expect(field).toHaveAttribute("min", "1");
    expect(field).toHaveAttribute("max", "50");
  });

  it("shows the default as the value, not as placeholder grey", () => {
    // A row of empty boxes under a capability that will happily run reads as
    // decisions still to make. Nothing is stored by showing it, so the field
    // keeps tracking the default if it changes in code.
    renderForm();
    expect(screen.getByLabelText(/Default top k/)).toHaveValue(5);
  });

  it("reports a number as a number, not a string", async () => {
    // Typed onto a stored value rather than into an empty box: the form is
    // controlled by its caller, which here is a spy rather than state, so the
    // field keeps showing what it was rendered with - and a field with a default
    // is never empty to begin with.
    const onChange = renderForm({ default_top_k: 1 });

    await userEvent.type(screen.getByLabelText(/Default top k/), "2");

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ default_top_k: 12 }));
  });

  it("clearing a field unsets it rather than sending zero", async () => {
    // Zero and "unset" mean different things: unset falls back to the
    // capability's own default.
    const onChange = vi.fn();
    render(
      <SchemaForm
        schema={SCHEMA}
        value={{ default_top_k: 8 }}
        onChange={onChange}
        idPrefix="knowledge"
      />,
    );
    await userEvent.clear(screen.getByLabelText(/Default top k/));
    expect(onChange).toHaveBeenLastCalledWith({ default_top_k: undefined });
  });

  it("types into a text field one character at a time, keeping what is there", async () => {
    // The form is controlled by its caller and this one holds a spy rather than
    // state, so the assertion is about the first keystroke: a string field sends
    // the string, never a number and never `undefined`.
    const onChange = renderForm({ tool_name: "search" });

    await userEvent.type(screen.getByLabelText(/Tool name/), "!");

    expect(onChange).toHaveBeenLastCalledWith({ tool_name: "search!" });
  });

  it("clearing a text field unsets it too", async () => {
    const onChange = vi.fn();
    render(
      <SchemaForm
        schema={SCHEMA}
        value={{ tool_name: "search_orders" }}
        onChange={onChange}
        idPrefix="knowledge"
      />,
    );
    await userEvent.clear(screen.getByLabelText(/Tool name/));
    expect(onChange).toHaveBeenLastCalledWith({ tool_name: undefined });
  });

  it("enforces the schema's max length on a string", () => {
    renderForm();
    expect(screen.getByLabelText(/Tool name/)).toHaveAttribute("maxlength", "64");
  });

  it("renders a boolean as a switch and reports the toggle", async () => {
    const onChange = renderForm();
    await userEvent.click(screen.getByRole("switch", { name: /Verbose/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ verbose: true }));
  });

  it("shows a switch whose default is on as on", () => {
    // The same rule as every other field: what is drawn is what will happen if
    // nobody touches it, and a switch drawn off over a capability that will run
    // with it on is the one shape of this that misleads silently.
    render(
      <SchemaForm
        schema={{ type: "object", properties: { verbose: { type: "boolean", default: true } } }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="x"
      />,
    );

    expect(screen.getByRole("switch", { name: /Verbose/ })).toBeChecked();
  });

  it("shows a switch somebody turned off as off, over a default of on", () => {
    render(
      <SchemaForm
        schema={{ type: "object", properties: { verbose: { type: "boolean", default: true } } }}
        value={{ verbose: false }}
        onChange={vi.fn()}
        idPrefix="x"
      />,
    );

    expect(screen.getByRole("switch", { name: /Verbose/ })).not.toBeChecked();
  });

  it("keeps the other fields when one changes", async () => {
    const onChange = vi.fn();
    render(
      <SchemaForm
        schema={SCHEMA}
        value={{ tool_name: "search_orders" }}
        onChange={onChange}
        idPrefix="knowledge"
      />,
    );
    await userEvent.click(screen.getByRole("switch", { name: /Verbose/ }));
    expect(onChange).toHaveBeenLastCalledWith({ tool_name: "search_orders", verbose: true });
  });

  it("renders a closed set of values as a select, not a text box", () => {
    // A `Literal` is a string, so without the enum check first this would be a
    // field where anything can be typed and only the backend says no.
    renderForm();
    expect(screen.getByRole("combobox", { name: /Effort/ })).toBeInTheDocument();
  });

  it("shows a stored choice", () => {
    renderForm({ effort: "high" });
    expect(screen.getByRole("combobox", { name: /Effort/ })).toHaveTextContent("high");
  });

  it("labels a choice with what it does, when the schema says", async () => {
    // `clear_tool_results` in a dropdown is a decision somebody makes by
    // guessing, and the guess that costs money is the one that picks the
    // summarising strategy.
    render(
      <SchemaForm
        schema={{
          type: "object",
          properties: {
            strategy: {
              type: "string",
              default: "tiered",
              enum: ["tiered", "summarize"],
              "x-enum-labels": {
                tiered: "Tiered - clear tool results first",
                summarize: "Summarise older messages - one model call per run",
              },
            },
          },
        }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="compaction"
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: /Strategy/ }));
    expect(
      screen.getByRole("option", { name: "Summarise older messages - one model call per run" }),
    ).toBeInTheDocument();
  });

  it("shows an unlabelled choice verbatim rather than prettifying it", () => {
    // Several of these are identifiers a person recognises - a tool id, an
    // effort level - and a picker that renamed one would be storing something
    // other than what it displayed.
    renderForm({ effort: "medium" });
    expect(screen.getByRole("combobox", { name: /Effort/ })).toHaveTextContent("medium");
  });

  it("preselects an enum's default rather than offering to leave it unset", () => {
    // With a default, "Not set" and the default are the same behaviour under two
    // names, and one of them tells the reader nothing about what will happen.
    render(
      <SchemaForm
        schema={{
          type: "object",
          properties: { strategy: { type: "string", default: "tiered", enum: ["tiered", "off"] } },
        }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="compaction"
      />,
    );

    expect(screen.getByRole("combobox", { name: /Strategy/ })).toHaveTextContent("tiered");
  });

  it("shows an optional enum nobody has answered as unset", () => {
    // Not as the first option, which would claim a choice was made - and for
    // this field that choice is what turns thinking on.
    renderForm();
    expect(screen.getByRole("combobox", { name: /Effort/ })).toHaveTextContent("Not set");
  });

  it("records the choice that was picked from a closed set", async () => {
    const onChange = renderForm();

    await userEvent.click(screen.getByRole("combobox", { name: /Effort/ }));
    await userEvent.click(screen.getByRole("option", { name: "high" }));

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ effort: "high" }));
  });

  it("unsets an enum by dropping the key, not by storing the word", async () => {
    // The same rule the rest of this form follows: an unanswered field defers to
    // the capability's own default, and "Not set" is not a value the backend
    // accepts.
    const onChange = renderForm({ effort: "high" });

    await userEvent.click(screen.getByRole("combobox", { name: /Effort/ }));
    await userEvent.click(screen.getByRole("option", { name: "Not set" }));

    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("leaves a field with no default empty rather than inventing one", async () => {
    // A shown value is the schema's default. Inventing one for a field that has
    // none would read as a value the capability would use.
    render(
      <SchemaForm
        schema={{
          type: "object",
          properties: {
            retries: { type: "integer" },
            base_url: { type: "string", default: "https://api.acme.com" },
            // Pydantic writes this for every optional field, and it is the
            // absence of a default rather than one - rendered, it would put the
            // word `null` in the box.
            proxy: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
          },
        }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="x"
      />,
    );

    expect(screen.getByLabelText(/Retries/)).toHaveValue(null);
    expect(screen.getByLabelText(/Base url/)).toHaveValue("https://api.acme.com");
    expect(screen.getByLabelText(/Proxy/)).toHaveValue("");
  });

  it("does not accept edits when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(
      <SchemaForm schema={SCHEMA} value={{}} onChange={onChange} idPrefix="knowledge" disabled />,
    );
    await userEvent.type(screen.getByLabelText(/Tool name/), "x");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows what the server said about one field, beside that field", () => {
    render(
      <SchemaForm
        schema={SCHEMA}
        value={{}}
        onChange={vi.fn()}
        idPrefix="knowledge"
        errors={{ tool_name: "That name is already taken" }}
      />,
    );

    expect(screen.getByText("That name is already taken")).toBeInTheDocument();
    expect(screen.getByLabelText(/Tool name/)).toBeInvalid();
    // Only that one: marking every input would say the whole form is wrong.
    expect(screen.getByLabelText(/Default top k/)).not.toBeInvalid();
  });
});

/**
 * What a Pydantic secret payload looks like in JSON Schema, and the two things
 * about it this form has to get right.
 */
describe("SchemaForm on a secret payload", () => {
  const SECRET: JsonSchema = {
    type: "object",
    properties: {
      // Every payload states its own discriminator this way.
      kind: { const: "azure_openai", default: "azure_openai", type: "string", title: "Kind" },
      api_key: { type: "string", format: "password", title: "Api Key" },
      azure_endpoint: { type: "string", title: "Azure Endpoint" },
    },
    required: ["api_key", "azure_endpoint"],
  };

  it("omits a field with exactly one legal value", () => {
    // The caller supplies the kind. A control for it could only ever be wrong,
    // and here it would be a text box next to the picker that already chose it.
    render(<SchemaForm schema={SECRET} value={{}} onChange={vi.fn()} idPrefix="secret" />);
    expect(screen.queryByLabelText(/^Kind/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Azure Endpoint/)).toBeInTheDocument();
  });

  it("masks a field the schema marks as a password", () => {
    render(<SchemaForm schema={SECRET} value={{}} onChange={vi.fn()} idPrefix="secret" />);
    expect(screen.getByLabelText(/Api Key/, { selector: "input" })).toHaveAttribute(
      "type",
      "password",
    );
    expect(screen.getByLabelText(/Azure Endpoint/)).not.toHaveAttribute("type", "password");
  });

  it("renders nothing for a schema whose only property is its discriminator", () => {
    // Not an empty card with a heading over it: a shape with no fields to fill
    // in has no form.
    const { container } = render(
      <SchemaForm
        schema={{ type: "object", properties: { kind: { const: "none", type: "string" } } }}
        value={{}}
        onChange={vi.fn()}
        idPrefix="secret"
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

/** Two masked fields and one plain one, which is what an AWS pair looks like. */
const AWS_SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    aws_access_key_id: { type: "string", title: "Aws Access Key Id" },
    aws_secret_access_key: { type: "string", format: "password", title: "Aws Secret Access Key" },
    aws_session_token: { type: "string", format: "password", title: "Aws Session Token" },
  },
  required: ["aws_access_key_id", "aws_secret_access_key"],
};

describe("SchemaForm · reading back what was pasted", () => {
  it("reveals one secret field without unmasking the others", async () => {
    // A key is pasted, never typed, and a paste that went wrong - a trailing
    // newline, half a value, the wrong clipboard entry - is invisible behind
    // dots. The vault never shows a stored secret again, so this is the only
    // moment the value can be checked at all.
    render(<SchemaForm schema={AWS_SCHEMA} value={{}} onChange={vi.fn()} idPrefix="secret" />);

    await userEvent.click(screen.getByRole("button", { name: "Show Aws Secret Access Key" }));

    expect(
      screen.getByLabelText(/Aws Secret Access Key/, { selector: "input" }),
    ).not.toHaveAttribute("type", "password");
    expect(screen.getByLabelText(/Aws Session Token/, { selector: "input" })).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("hides it again", async () => {
    render(<SchemaForm schema={AWS_SCHEMA} value={{}} onChange={vi.fn()} idPrefix="secret" />);

    await userEvent.click(screen.getByRole("button", { name: "Show Aws Secret Access Key" }));
    await userEvent.click(screen.getByRole("button", { name: "Hide Aws Secret Access Key" }));

    expect(screen.getByLabelText(/Aws Secret Access Key/, { selector: "input" })).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("offers nothing to reveal on a field that was never masked", () => {
    render(<SchemaForm schema={AWS_SCHEMA} value={{}} onChange={vi.fn()} idPrefix="secret" />);

    expect(screen.queryByRole("button", { name: /Aws Access Key Id/ })).toBeNull();
  });
});
