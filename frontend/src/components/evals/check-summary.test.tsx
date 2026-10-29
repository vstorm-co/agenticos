import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CaseCheck } from "@/types/datasets";
import { CheckSummary } from "./check-summary";
import { VerdictBadge } from "./verdict-badge";

function said(check: CaseCheck) {
  const { container, unmount } = render(<CheckSummary check={check} />);
  const element = container.firstElementChild as HTMLElement;
  const result = { text: element.textContent, title: element.getAttribute("title") };
  unmount();
  return result;
}

describe("CheckSummary", () => {
  it("reads a pattern that is only a word as mentioning it, with the pattern on hover", () => {
    expect(said({ type: "regex", value: "(?i)manager" })).toEqual({
      text: "Mentions “manager” (any case)",
      title: "regex (?i)manager",
    });
    expect(said({ type: "regex", value: "manager", case_sensitive: true }).text).toBe(
      "Mentions “manager” (exact case)",
    );
  });

  it("quotes a real pattern as written, and (?i) wins over case sensitivity", () => {
    expect(said({ type: "regex", value: "30 (days|dni)" }).text).toBe(
      "Matches the pattern “30 (days|dni)” (any case)",
    );
    expect(said({ type: "regex", value: "(?i)a.b", case_sensitive: true }).text).toBe(
      "Matches the pattern “(?i)a.b” (any case)",
    );
  });

  it("says each text rule, and where in a JSON answer it looks", () => {
    expect(said({ type: "contains", value: "30 days" }).text).toBe("Mentions “30 days” (any case)");
    expect(said({ type: "not_contains", value: "sorry", case_sensitive: true }).text).toBe(
      "Does not mention “sorry” (exact case)",
    );
    expect(said({ type: "equals", value: "Yes", path: "answer.ok" }).text).toBe(
      "In answer.ok: Is exactly “Yes” (any case)",
    );
  });

  it("says the ceilings, the schema and the judge's criterion in words", () => {
    expect(said({ type: "max_cost_usd", value: 0.05 }).text).toBe("Costs at most $0.05");
    expect(said({ type: "max_latency_ms", value: 2500 }).text).toBe("Answers within 2.5s");
    expect(said({ type: "json_schema", schema: { type: "object" } })).toEqual({
      text: "The answer matches a JSON schema",
      title: 'json_schema {"schema":{"type":"object"}}',
    });
    expect(said({ type: "judge", criterion: "Names the policy" }).text).toBe(
      "Judged on: Names the policy",
    );
  });

  it("says a length check's bounds in its unit, and where in a JSON answer", () => {
    expect(said({ type: "length", unit: "words", max: 50 })).toEqual({
      text: "At most 50 words",
      title: 'length {"unit":"words","max":50}',
    });
    expect(said({ type: "length", min: 1 }).text).toBe("At least 1 character");
    expect(said({ type: "length", unit: "words", min: 1 }).text).toBe("At least 1 word");
    expect(said({ type: "length", unit: "characters", max: 280 }).text).toBe(
      "At most 280 characters",
    );
    expect(said({ type: "length", unit: "words", min: 20, max: 60, path: "summary" }).text).toBe(
      "In summary: Between 20 and 60 words",
    );
    expect(said({ type: "length", unit: "characters", min: 2, max: 9 }).text).toBe(
      "Between 2 and 9 characters",
    );
  });

  it("shows a check type it does not know as stored", () => {
    render(<CheckSummary check={{ type: "future_rule", value: "x" }} />);
    expect(screen.getByText("future_rule x").tagName).toBe("CODE");
  });
});

describe("VerdictBadge", () => {
  it.each([
    ["pass", "bg-success/10", "text-success"],
    ["fail", "bg-destructive/10", "text-destructive"],
    ["undecided", "bg-secondary", "text-muted-foreground"],
    ["error", "bg-warning/10", "text-warning"],
  ] as const)("tints a %s verdict and colours its icon", (tone, tint, color) => {
    render(<VerdictBadge tone={tone}>{tone}</VerdictBadge>);
    const badge = screen.getByText(tone);
    expect(badge).toHaveClass(tint);
    expect(badge.querySelector("svg")).toHaveClass(color);
  });
});
