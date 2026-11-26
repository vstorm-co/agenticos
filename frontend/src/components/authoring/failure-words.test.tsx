import { render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { authoringRequest } from "@/test-utils/authoring";
import type { AuthoringFailure } from "@/types/authoring";
import type { ImprovementFailure } from "@/types/improvement";
import { RequestFailure, useFailureWords } from "./failure-words";

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

const SHARED = {
  system_agent_not_seeded: {},
  system_agent_missing: {},
  system_agent_unpublished: {},
  system_agent_archived: {},
  system_agent_no_access: {},
  system_agent_no_model: {},
  system_agent_failed: {},
  only_anonymised: {},
  all_evidence: {},
  no_scorer: {},
  no_reruns: {},
  evidence_too_large: {},
  budget: {},
  not_found: {},
  not_allowed: {},
  changed: {},
  run_failed: {},
  refused: {},
  failed: {},
};

const SESSION: Record<ImprovementFailure, Record<string, number>> = {
  ...SHARED,
  too_few_held_out: { missing: 3 },
  no_evidence: {},
  search_too_few_training: { minimum: 10 },
};

const REQUEST: Record<AuthoringFailure, Record<string, number>> = {
  ...SHARED,
  no_runs_view: {},
  evidence_erased: {},
  no_edit_agent: {},
  agent_gone: {},
  no_published_version: {},
  skill_gone: {},
  no_edit_skill: {},
  session_moved_on: {},
  conflicts_unanswered: {},
  session_stopped: {},
  context_gone: {},
  no_edit_context: {},
  unknown_skill_use: { runs: 5 },
  no_evidence: {},
  key_revoked: {},
  not_a_member: {},
  unexpected: {},
  stalled: {},
  withdrawn: {},
};

function words(of: "session" | "request") {
  return renderHook(() => useFailureWords(of)).result.current;
}

describe.each([
  ["session", SESSION],
  ["request", REQUEST],
] as const)("a stored %s failure, in Polish", (of, codes) => {
  it.each(Object.entries(codes))("words %s in the reader's language", (code, params) => {
    const said = words(of)({ error: ENGLISH, error_code: code, error_params: params });
    expect(said.text).not.toBe(ENGLISH);
    expect(said.text).not.toMatch(/[{}]/);
    expect(said.text?.length).toBeGreaterThan(10);
    // A refusal's sentence names which agent or dataset; a fixed one says nothing more.
    expect(said.detail).toBe(code in SHARED ? ENGLISH : null);
  });

  it("shows the stored sentence for a code this console does not know", () => {
    expect(words(of)({ error: ENGLISH, error_code: "something_new" })).toEqual({
      text: ENGLISH,
      detail: null,
    });
  });

  it("shows the stored sentence when there is no code", () => {
    expect(words(of)({ error: ENGLISH, error_code: null })).toEqual({
      text: ENGLISH,
      detail: null,
    });
    expect(words(of)({ error: null })).toEqual({ text: null, detail: null });
  });
});

describe("the counts a failure names", () => {
  it("words them in the reader's plural", () => {
    expect(
      words("session")({
        error: ENGLISH,
        error_code: "too_few_held_out",
        error_params: { missing: 3 },
      }).text,
    ).toBe("Dodaj jeszcze 3 pytania kontrolne, żeby zmierzyć zmianę.");
    expect(
      words("request")({
        error: ENGLISH,
        error_code: "unknown_skill_use",
        error_params: { runs: 5 },
      }).text,
    ).toContain("5 ocenionych negatywnie albo nieudanych runów");
  });

  it("shows the stored sentence for a code sent without its count", () => {
    const said = words("session")({
      error: ENGLISH,
      error_code: "search_too_few_training",
      error_params: { missing: 10 },
    });
    expect(said.text).toBe(ENGLISH);
  });

  it("keeps a session's codes and a request's apart", () => {
    expect(words("request")({ error: ENGLISH, error_code: "too_few_held_out" }).text).toBe(ENGLISH);
    expect(words("session")({ error: ENGLISH, error_code: "no_evidence" }).text).toBe(
      "Nie ma jeszcze ocenionych runów czatu ani porażek na pytaniach treningowych.",
    );
  });
});

describe("RequestFailure", () => {
  it("keeps a refusal's own sentence under Technical details", () => {
    render(
      <RequestFailure
        request={authoringRequest({
          status: "failed",
          error: "'Improver' cannot reach its model: no key",
          error_code: "system_agent_no_model",
        })}
        className="text-xs"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Agent systemowy, którego potrzebuje ten krok, nie może połączyć się ze swoim modelem.",
    );
    const details = screen.getByText("Szczegóły techniczne").closest("details");
    expect(details).toHaveTextContent("'Improver' cannot reach its model: no key");
    expect(screen.getByText("'Improver' cannot reach its model: no key")).toHaveAttribute(
      "lang",
      "en",
    );
  });

  it("says a fixed failure once, in the reader's language", () => {
    render(
      <RequestFailure
        request={authoringRequest({
          status: "failed",
          error: "The context file is gone.",
          error_code: "context_gone",
        })}
        className="text-xs"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Plik kontekstu już nie istnieje.");
    expect(screen.queryByText("Szczegóły techniczne")).not.toBeInTheDocument();
  });
});
