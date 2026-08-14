import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SecretsTable } from "./secrets-table";
import type { Secret, SecretPurpose } from "@/types/secrets";

/**
 * The service filter, in the controls strip - not the second header row it
 * used to draw under the column names, which was the one filter in the product
 * living outside the shared list-card pattern.
 */

function secret(overrides: Partial<Secret>): Secret {
  return {
    id: crypto.randomUUID(),
    name: "a-key",
    hint: "abcd",
    kind: "api_key",
    purpose: "custom",
    visibility: "private",
    shared_with: 0,
    created_by_email: "kim@acme.test",
    created_by_avatar_url: null,
    used_by: [],
    ...overrides,
  } as Secret;
}

const PURPOSES: SecretPurpose[] = [{ id: "openai", label: "OpenAI" } as SecretPurpose];

const noop = vi.fn();

function renderTable(secrets: Secret[]) {
  return render(
    <SecretsTable
      secrets={secrets}
      purposes={PURPOSES}
      canManage={false}
      onShare={noop}
      onRotate={noop}
      onDelete={noop}
    />,
  );
}

describe("the service filter", () => {
  it("narrows the keys to one service, and back to all of them", async () => {
    renderTable([
      secret({ name: "openai-prod", purpose: "openai" }),
      secret({ name: "internal-token", purpose: "custom" }),
    ]);

    expect(screen.getByText("openai-prod")).toBeInTheDocument();
    expect(screen.getByText("internal-token")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by service" }));
    await userEvent.click(screen.getByRole("option", { name: "OpenAI" }));

    expect(screen.getByText("openai-prod")).toBeInTheDocument();
    expect(screen.queryByText("internal-token")).toBeNull();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by service" }));
    await userEvent.click(screen.getByRole("option", { name: "Any service" }));

    expect(screen.getByText("internal-token")).toBeInTheDocument();
  });

  it("offers only the services actually present, each once", async () => {
    renderTable([
      secret({ name: "one", purpose: "openai" }),
      secret({ name: "two", purpose: "openai" }),
    ]);

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by service" }));

    expect(screen.getAllByRole("option", { name: "OpenAI" })).toHaveLength(1);
    expect(screen.queryByRole("option", { name: "Custom service" })).toBeNull();
  });
});
