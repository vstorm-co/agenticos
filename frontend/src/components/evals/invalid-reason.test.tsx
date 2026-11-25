import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { InvalidReasonCode } from "@/types/eval-runs";
import { IncomparableResult } from "@/components/improvement/incomparable-result";
import { InvalidReason } from "./invalid-reason";

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const pl = (await import("../../../messages/pl.json")).default;
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({
        locale: "pl",
        messages: pl as never,
        namespace: namespace as never,
      }),
  };
});

const ENGLISH = "A sentence the server wrote in English.";

const CODES: InvalidReasonCode[] = [
  "knowledge_not_retrieved",
  "too_few_held_out",
  "scoring_changed",
  "judge_changed_mid_run",
  "judge_instructions_changed",
  "judge_differs",
  "knowledge_draft_changed",
  "held_out_ungraded",
];

describe("a reason two sides cannot be compared, in Polish", () => {
  it.each(CODES)("words %s in the reader's language", (code) => {
    const { container } = render(
      <InvalidReason
        comparison={{
          invalid_reason: ENGLISH,
          invalid_reason_code: code,
          invalid_reason_params: { missing: 3 },
        }}
      />,
    );
    expect(container).not.toHaveTextContent(ENGLISH);
    expect(container.textContent).not.toMatch(/[{}]/);
    expect(container.textContent?.length).toBeGreaterThan(10);
  });

  it("names the number of questions still missing", () => {
    render(
      <InvalidReason
        comparison={{
          invalid_reason: ENGLISH,
          invalid_reason_code: "too_few_held_out",
          invalid_reason_params: { missing: 3 },
        }}
      />,
    );
    expect(
      screen.getByText("Dodaj jeszcze 3 pytania kontrolne, żeby zmierzyć zmianę."),
    ).toBeVisible();
  });

  it("shows the server's sentence for a code it does not know, or none", () => {
    const { rerender } = render(
      <InvalidReason
        comparison={{
          invalid_reason: ENGLISH,
          invalid_reason_code: "from_a_newer_server" as InvalidReasonCode,
        }}
      />,
    );
    expect(screen.getByText(ENGLISH)).toBeVisible();
    rerender(<InvalidReason comparison={{ invalid_reason: ENGLISH, invalid_reason_code: null }} />);
    expect(screen.getByText(ENGLISH)).toBeVisible();
  });

  it("reads a code sent without the numbers its words need as the server's sentence", () => {
    render(
      <InvalidReason
        comparison={{ invalid_reason: ENGLISH, invalid_reason_code: "too_few_held_out" }}
      />,
    );
    expect(screen.getByText(ENGLISH)).toBeVisible();
  });

  it("draws nothing when the sides can be compared", () => {
    const { container } = render(
      <InvalidReason comparison={{ invalid_reason: null, invalid_reason_code: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

it("words an Improve result that cannot be compared in Polish, not the server's English", () => {
  render(
    <IncomparableResult
      agentId="a1"
      runId="r1"
      comparison={{
        invalid_reason: "The two sides were graded by a different judge, model or rubric.",
        invalid_reason_code: "judge_differs",
      }}
    />,
  );
  expect(screen.getByText("Strony oceniał inny sędzia, model albo inna rubryka.")).toBeVisible();
  expect(screen.queryByText(/different judge/)).not.toBeInTheDocument();
});
