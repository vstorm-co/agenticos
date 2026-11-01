import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerToField } from "./answer-to-field";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("AnswerToField", () => {
  it("says what the chosen destination means", () => {
    render(<AnswerToField value="primary" onChange={vi.fn()} />);

    expect(screen.getByText("answerToHint.primary")).toBeInTheDocument();
    expect(screen.getByText("answerToLabel")).toBeInTheDocument();
  });

  it("keeps showing a routine made for one chat as such", () => {
    render(<AnswerToField value="conversation" onChange={vi.fn()} />);

    expect(screen.getByText("answerToHint.conversation")).toBeInTheDocument();
  });
});
