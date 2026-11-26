import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WhatsAppLateTemplateField } from "./whatsapp-late-template-field";
import type { WhatsAppTemplate } from "@/types/channels";

const state = vi.hoisted(() => ({
  query: {} as { data?: WhatsAppTemplate[]; isLoading: boolean; isError: boolean },
}));

vi.mock("@/hooks/use-channel-bots", () => ({
  useWhatsAppTemplates: () => state.query,
}));

const ANSWER: WhatsAppTemplate = {
  name: "late_answer",
  language: "en_US",
  body: "Your answer is ready: {{1}} - thanks",
};
const OTHER: WhatsAppTemplate = { name: "follow_up", language: "pl", body: "Odpowiedź: {{1}}" };

function mount(value: { name: string; language: string } | null = null) {
  const onChange = vi.fn();
  render(<WhatsAppLateTemplateField botId="b1" value={value} onChange={onChange} />);
  return onChange;
}

beforeEach(() => {
  state.query = { data: [ANSWER, OTHER], isLoading: false, isError: false };
});

describe("the late-answer template field (#2076)", () => {
  it("lists Meta's usable templates with their text", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Late-answer template"));
    expect(screen.getByRole("option", { name: "None" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "follow_up · pl" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "late_answer · en_US" }));

    expect(onChange).toHaveBeenCalledWith({ name: "late_answer", language: "en_US" });
  });

  it("shows the chosen template's text under the field, and null for None", async () => {
    const onChange = mount({ name: "late_answer", language: "en_US" });

    expect(screen.getByText(ANSWER.body)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Late-answer template"));
    await userEvent.click(screen.getByRole("option", { name: "None" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says so when Meta lists none", () => {
    state.query = { data: [], isLoading: false, isError: false };
    mount();

    expect(screen.getByText(/lists no approved utility template/i)).toBeInTheDocument();
  });

  it("says the list could not be loaded rather than showing none", () => {
    state.query = { data: undefined, isLoading: false, isError: true };
    mount();

    expect(screen.getByRole("alert")).toHaveTextContent(/could not load the templates from Meta/i);
    expect(screen.queryByText(/lists no approved utility template/i)).toBeNull();
  });

  it("says it is loading", () => {
    state.query = { data: undefined, isLoading: true, isError: false };
    mount();

    expect(screen.getByText("Loading templates…")).toBeInTheDocument();
    expect(screen.queryByText(/lists no approved utility template/i)).toBeNull();
  });

  it("marks a stored template Meta no longer lists", async () => {
    mount({ name: "withdrawn", language: "en_US" });

    expect(screen.getByText(/withdrawn · en_US/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Late-answer template"));
    expect(
      screen.getByRole("option", { name: /withdrawn · en_US.*no longer lists it as usable/ }),
    ).toBeInTheDocument();
  });

  it("shows the stored template's text while the list loads or after Meta dropped it", () => {
    const stored = { name: "withdrawn", language: "en_US", body: "Old text: {{1}} - bye" };
    state.query = { data: undefined, isLoading: true, isError: false };
    const view = render(
      <WhatsAppLateTemplateField
        botId="b1"
        value={{ name: "withdrawn", language: "en_US" }}
        stored={stored}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(stored.body)).toBeInTheDocument();
    view.unmount();

    state.query = { data: [ANSWER], isLoading: false, isError: false };
    render(
      <WhatsAppLateTemplateField
        botId="b1"
        value={{ name: "withdrawn", language: "en_US" }}
        stored={stored}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(stored.body)).toBeInTheDocument();
  });

  it("does not call a stored template unlisted when the list failed to load", () => {
    state.query = { data: undefined, isLoading: false, isError: true };
    mount({ name: "late_answer", language: "en_US" });

    expect(screen.queryByText(/no longer lists it/)).toBeNull();
    expect(screen.getByText(/late_answer · en_US/)).toBeInTheDocument();
  });
});
