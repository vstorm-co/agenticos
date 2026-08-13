import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WidgetFields } from "./widget-fields";
import { DEFAULT_WIDGET_CONFIG, type WidgetConfig } from "@/types/embeds";

/**
 * Every field of the bubble that runs on somebody else's page.
 *
 * The reason this file exists is what it pins: six of these seven were stored,
 * validated and published to `widget.js` while the Builder edited only the accent
 * - so every widget this platform is pasted into said *Ask us anything* over a
 * button labelled *Chat*, and the only way to change either was an API call.
 */

const onChange = vi.fn();

function fields(config: Partial<WidgetConfig> = {}) {
  render(
    <WidgetFields
      config={{ ...DEFAULT_WIDGET_CONFIG, ...config }}
      disabled={false}
      onChange={onChange}
    />,
  );
}

beforeEach(() => onChange.mockClear());

describe("what the bubble says", () => {
  it("carries the header", async () => {
    fields({ title: "" });

    await userEvent.type(screen.getByLabelText("Header"), "R");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ title: "R" }));
  });

  it("carries the line under it", async () => {
    fields();

    await userEvent.type(screen.getByLabelText("Under the header"), "R");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ subtitle: "R" }));
  });

  it("carries the greeting", async () => {
    fields({ greeting: "" });

    await userEvent.type(screen.getByLabelText("First thing it says"), "H");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ greeting: "H" }));
  });

  it("says the greeting never reaches the model", () => {
    // A greeting in the model's history is a turn the agent thinks it took.
    fields();

    expect(screen.getByText(/never sent to the model/)).toBeInTheDocument();
  });

  it("carries what the empty box says", async () => {
    fields({ placeholder: "" });

    await userEvent.type(screen.getByLabelText("In the empty box"), "A");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ placeholder: "A" }));
  });

  it("carries what the button says", async () => {
    fields({ launcher_label: "" });

    await userEvent.type(screen.getByLabelText("On the button"), "H");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ launcher_label: "H" }));
  });
});

describe("where the bubble sits and what colour it is", () => {
  it("carries the corner", async () => {
    fields();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Bottom left" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ position: "left" }));
  });

  it("carries an accent picked from the swatch", () => {
    fields();

    fireEvent.change(screen.getAllByLabelText("Accent colour")[0]!, {
      target: { value: "#00ff00" },
    });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ accent: "#00ff00" }));
  });

  it("carries an accent typed as hex", async () => {
    fields({ accent: "" });

    await userEvent.type(screen.getAllByLabelText("Accent colour")[1]!, "#");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ accent: "#" }));
  });
});
