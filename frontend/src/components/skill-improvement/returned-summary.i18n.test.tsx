import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ReturnRefusal, ReturnedToMain } from "@/types/skill-merge";
import { ReturnedSummary } from "./returned-summary";

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const pl = (await import("../../../messages/pl.json")).default;
  return {
    ...actual,
    useLocale: () => "pl",
    useTranslations: (namespace?: string) =>
      actual.createTranslator({
        locale: "pl",
        messages: pl as never,
        namespace: namespace as never,
      }),
  };
});

const ENGLISH = "A sentence the server wrote in English.";

function summary(code: ReturnRefusal | null | undefined): ReturnedToMain {
  return {
    agents: [
      {
        agent: { id: "outlet", name: "Outlet" },
        published: false,
        agent_version: null,
        refused: ENGLISH,
        refused_code: code,
      },
    ],
    hidden: 0,
    remaining: 1,
    archived: false,
  };
}

const CODES: ReturnRefusal[] = [
  "agent_not_found",
  "workflow_agent",
  "architect_admin_only",
  "system_agent_admin_only",
  "via_specialist",
  "not_bound",
  "binding_problems",
  "system_agent_parts",
  "does_not_publish",
];

it.each(CODES)("says in Polish why an agent stays on the fork: %s", (code) => {
  render(<ReturnedSummary returned={summary(code)} />);
  const line = screen.getByText(/^Outlet zostaje na forku: /);
  expect(line).not.toHaveTextContent(ENGLISH);
  expect(line.textContent).not.toMatch(/[{}]/);
});

it("names a specialist binding in Polish", () => {
  render(<ReturnedSummary returned={summary("via_specialist")} />);
  expect(
    screen.getByText(
      "Outlet zostaje na forku: używa skilla tylko przez specjalistę, którego zmienia się w Builderze agenta",
    ),
  ).toBeVisible();
});

it("keeps the server's sentence for a refusal it has no code for", () => {
  const { rerender } = render(<ReturnedSummary returned={summary(null)} />);
  expect(screen.getByText(`Outlet zostaje na forku: ${ENGLISH}`)).toBeVisible();
  rerender(<ReturnedSummary returned={summary("from_a_newer_server" as ReturnRefusal)} />);
  expect(screen.getByText(`Outlet zostaje na forku: ${ENGLISH}`)).toBeVisible();
});
