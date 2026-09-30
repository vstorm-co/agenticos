import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerFormatForm } from "./answer-format-form";
import { fieldsOf, parseSchema, schemaOf, type AnswerField } from "./answer-format";

const SCORE: AnswerField[] = [
  { name: "score", type: "integer", description: "0 to 100", required: true },
  { name: "tags", type: "string_list", description: "", required: false },
];

const SCORE_SCHEMA = {
  type: "object",
  properties: {
    score: { type: "integer", description: "0 to 100" },
    tags: { type: "array", items: { type: "string" } },
  },
  required: ["score"],
  additionalProperties: false,
};

describe("answer format", () => {
  it("writes a field list as an object schema, leaving out a row with no name", () => {
    expect(
      schemaOf([...SCORE, { name: " ", type: "string", description: "", required: true }]),
    ).toEqual(SCORE_SCHEMA);
  });

  it("reads back a schema the list can say, and refuses one it cannot", () => {
    expect(fieldsOf(SCORE_SCHEMA)).toEqual(SCORE);
    expect(fieldsOf({ type: "object" })).toEqual([]);
    for (const schema of [
      { type: "array" },
      { type: "object", title: "x" },
      { type: "object", properties: [] },
      { type: "object", properties: { a: "text" } },
      { type: "object", properties: { a: { type: "string", enum: ["x"] } } },
      { type: "object", properties: { a: { type: "array", items: { type: "integer" } } } },
      { type: "object", properties: { a: { type: "array", items: "string" } } },
      { type: "object", properties: { a: { type: "string", items: {} } } },
      { type: "object", properties: { a: { type: "object" } } },
    ]) {
      expect(fieldsOf(schema)).toBeNull();
    }
  });

  it("parses the JSON editor's text into an object schema or says why not", () => {
    expect(parseSchema('{"type": "object"}')).toEqual({ type: "object" });
    expect(parseSchema("{")).toBe("notJson");
    expect(parseSchema('{"type": "array"}')).toBe("notObject");
  });
});

describe("AnswerFormatForm", () => {
  it("switches from text to fields, and back", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<AnswerFormatForm value={null} onChange={onChange} />);
    expect(screen.getByText("Free-form prose, as in a chat.")).toBeTruthy();

    await userEvent.click(screen.getByRole("combobox", { name: "It answers" }));
    await userEvent.click(screen.getByRole("option", { name: "With structured data" }));
    const first = onChange.mock.lastCall![0];
    expect(fieldsOf(first)).toEqual([
      { name: "answer", type: "string", description: "", required: true },
    ]);

    rerender(<AnswerFormatForm value={first} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "It answers" }));
    await userEvent.click(screen.getByRole("option", { name: "In text" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("edits, adds and removes fields", async () => {
    const onChange = vi.fn();
    render(<AnswerFormatForm value={SCORE_SCHEMA} onChange={onChange} />);

    fireEvent.change(screen.getAllByLabelText("Field")[0]!, { target: { value: "points" } });
    expect(fieldsOf(onChange.mock.lastCall![0])![0]!.name).toBe("points");
    fireEvent.change(screen.getByLabelText("What goes in points"), {
      target: { value: "Out of 10" },
    });
    await userEvent.click(screen.getAllByRole("checkbox")[1]!);
    expect(fieldsOf(onChange.mock.lastCall![0])![1]!.required).toBe(true);
    await userEvent.click(screen.getAllByRole("combobox", { name: "Type" })[0]!);
    await userEvent.click(screen.getByRole("option", { name: "Yes or no" }));
    expect(fieldsOf(onChange.mock.lastCall![0])![0]!.type).toBe("boolean");

    await userEvent.click(screen.getByRole("button", { name: "Add a field" }));
    // A row with no name yet stays on screen, though the schema leaves it out.
    expect(screen.getAllByLabelText("Field")).toHaveLength(3);
    expect(fieldsOf(onChange.mock.lastCall![0])).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Remove 3" }));
    expect(screen.getAllByLabelText("Field")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Remove tags" }));
    expect(screen.getByRole("button", { name: "Remove points" })).toHaveProperty("disabled", true);
  });

  it("opens a schema the fields cannot say as JSON, and edits it there", () => {
    const onChange = vi.fn();
    const nested = { type: "object", properties: { lead: { type: "object" } } };
    render(<AnswerFormatForm value={nested} onChange={onChange} />);

    const editor = screen.getByRole("textbox", { name: "JSON Schema" });
    expect(screen.queryByRole("button", { name: "Edit as fields" })).toBeNull();
    fireEvent.change(editor, { target: { value: "{" } });
    expect(screen.getByText("This is not valid JSON.")).toBeTruthy();
    fireEvent.change(editor, { target: { value: '{"type": "string"}' } });
    expect(screen.getByText(/must describe an object/)).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(editor, { target: { value: JSON.stringify(SCORE_SCHEMA) } });
    expect(onChange).toHaveBeenLastCalledWith(SCORE_SCHEMA);
  });

  it("goes from fields to JSON and back to fields", async () => {
    const onChange = vi.fn();
    render(<AnswerFormatForm value={SCORE_SCHEMA} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit as JSON Schema" }));
    expect(screen.getByRole("textbox", { name: "JSON Schema" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Edit as fields" }));
    expect(screen.getAllByLabelText("Field")).toHaveLength(2);
  });

  it("names the empty choice after the agent's own format in a workflow step", () => {
    render(<AnswerFormatForm value={null} onChange={vi.fn()} keepsOwn disabled />);
    expect(screen.getByText("As the agent answers")).toBeTruthy();
    expect(screen.getByText(/The agent's own answer format/)).toBeTruthy();
  });
});
