import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ReturnRefusal, ReturnedToMain } from "@/types/skill-merge";
import { ReturnedSummary } from "./returned-summary";

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const en = (await import("../../../messages/en.json")).default;
  return {
    ...actual,
    useLocale: () => "en",
    useTranslations: (namespace?: string) =>
      actual.createTranslator({
        locale: "en",
        messages: en as never,
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

it.each(CODES)("says in English why an agent stays on the fork: %s", (code) => {
  render(<ReturnedSummary returned={summary(code)} />);
  const line = screen.getByText(/^Outlet stays on the fork: /);
  expect(line).not.toHaveTextContent(ENGLISH);
  expect(line.textContent).not.toMatch(/[{}]/);
});

it("names a specialist binding in English", () => {
  render(<ReturnedSummary returned={summary("via_specialist")} />);
  expect(
    screen.getByText(
      "Outlet stays on the fork: it uses the skill only through a specialist, which is changed in the agent's Builder",
    ),
  ).toBeVisible();
});

it("keeps the server's sentence for a refusal it has no code for", () => {
  const { rerender } = render(<ReturnedSummary returned={summary(null)} />);
  expect(screen.getByText(`Outlet stays on the fork: ${ENGLISH}`)).toBeVisible();
  rerender(<ReturnedSummary returned={summary("from_a_newer_server" as ReturnRefusal)} />);
  expect(screen.getByText(`Outlet stays on the fork: ${ENGLISH}`)).toBeVisible();
});
