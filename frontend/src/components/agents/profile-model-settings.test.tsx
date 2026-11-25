import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProfileModelSettings } from "./profile-model-settings";

function Harness({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [params, setParams] = useState(initial);
  return (
    <>
      <ProfileModelSettings value={params} onChange={setParams} />
      <output data-testid="params">{JSON.stringify(params)}</output>
    </>
  );
}

async function choose(label: string, option: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

describe("background model defaults", () => {
  it("keeps untouched defaults absent and does not write on mount", () => {
    const change = vi.fn();
    render(<ProfileModelSettings value={{}} onChange={change} />);
    expect(screen.getByLabelText("Reasoning effort")).toHaveTextContent("Provider default");
    expect(change).not.toHaveBeenCalled();
  });

  it.each(["minimal", "low", "medium", "high", "xhigh", "max"])(
    "loads the saved %s effort",
    (thinking) => {
      render(<Harness initial={{ thinking }} />);
      expect(screen.getByLabelText("Reasoning effort")).toHaveTextContent(thinking);
    },
  );

  it("changes effort, disables it explicitly, and removes the override on reset", async () => {
    render(<Harness initial={{ vendor_option: { keep: true }, max_tokens: 6144 }} />);
    await choose("Reasoning effort", "low");
    expect(JSON.parse(screen.getByTestId("params").textContent ?? "")).toEqual({
      vendor_option: { keep: true },
      max_tokens: 6144,
      thinking: "low",
    });
    await choose("Reasoning effort", "Off");
    expect(screen.getByTestId("params")).toHaveTextContent('"thinking":false');
    await choose("Reasoning effort", "On · provider effort");
    expect(screen.getByTestId("params")).toHaveTextContent('"thinking":true');
    await choose("Reasoning effort", "Provider default");
    expect(screen.getByTestId("params")).not.toHaveTextContent('"thinking"');
  });

  it("loads generation limits and retains unrelated provider settings when editing or clearing", () => {
    render(
      <Harness
        initial={{
          temperature: 0.3,
          top_p: 0.8,
          max_tokens: 6144,
          timeout: 120,
          parallel_tool_calls: false,
          thinking: "low",
          vendor_option: "preserve",
        }}
      />,
    );
    const tokens = screen.getByLabelText("Max tokens");
    expect(tokens).toHaveValue(6144);
    fireEvent.change(tokens, { target: { value: "4096" } });
    expect(screen.getByTestId("params")).toHaveTextContent('"max_tokens":4096');
    fireEvent.change(tokens, { target: { value: "" } });
    expect(screen.getByTestId("params")).not.toHaveTextContent('"max_tokens"');
    expect(screen.getByTestId("params")).toHaveTextContent('"thinking":"low"');
    expect(screen.getByTestId("params")).toHaveTextContent('"vendor_option":"preserve"');
    expect(screen.getByTestId("params")).toHaveTextContent('"parallel_tool_calls":false');
  });

  it("distinguishes a saved custom reasoning configuration from provider defaults", () => {
    render(<Harness initial={{ thinking: { budget_tokens: 1024 } }} />);
    expect(screen.getByLabelText("Reasoning effort")).toHaveTextContent("Saved custom setting");
    expect(screen.getByTestId("params")).toHaveTextContent('"budget_tokens":1024');
  });

  it("gives simultaneous background forms independent labels and disables every control", () => {
    const { container } = render(
      <>
        <ProfileModelSettings value={{}} onChange={vi.fn()} disabled />
        <ProfileModelSettings value={{}} onChange={vi.fn()} />
      </>,
    );
    const ids = Array.from(container.querySelectorAll("[id]")).map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(screen.getAllByLabelText("Reasoning effort")[0]).toBeDisabled();
  });
});
