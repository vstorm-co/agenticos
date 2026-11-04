import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SecretsTable } from "./secrets-table";
import type { Secret, SecretPurpose } from "@/types/secrets";

/**
 * Every key the organization holds, one row each, named by what it is for.
 * There is no service filter over them: an organization holds a handful of
 * keys, and a select over five rows was a control nobody needed.
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
      onShare={noop}
      onRotate={noop}
      onDelete={noop}
    />,
  );
}

describe("the keys", () => {
  it("lists every key, each named by the service it is for", () => {
    renderTable([
      secret({ name: "Main OpenAI", purpose: "openai" }),
      secret({ name: "Scraper token" }),
    ]);

    expect(screen.getByText("Main OpenAI")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Scraper token")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("offers a manager the key's actions", async () => {
    const onRotate = vi.fn();
    render(
      <SecretsTable
        secrets={[secret({ name: "Main OpenAI", purpose: "openai", can_edit: true })]}
        purposes={PURPOSES}
        onShare={noop}
        onRotate={onRotate}
        onDelete={noop}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Rotate Main OpenAI" }));

    expect(onRotate).toHaveBeenCalled();
  });
});

describe("the rotate action", () => {
  it("is a reconnect for a ChatGPT sign-in, which is replaced by signing in again", async () => {
    const onRotate = vi.fn();
    const chatgpt = secret({
      name: "My ChatGPT",
      kind: "openai_codex",
      purpose: "openai_codex",
      can_edit: true,
    });
    render(
      <SecretsTable
        secrets={[chatgpt, secret({ name: "a-key", can_edit: true })]}
        purposes={PURPOSES}
        onShare={noop}
        onRotate={onRotate}
        onDelete={noop}
      />,
    );

    expect(screen.getByRole("button", { name: "Rotate a-key" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect My ChatGPT" }));

    expect(onRotate).toHaveBeenCalledWith(chatgpt);
  });
});

it("shows actions only on individually editable keys while retaining read-only metadata", async () => {
  const edit = secret({ name: "Granted key", can_edit: true });
  const read = secret({ name: "Read-only key", can_edit: false });
  const onShare = vi.fn(),
    onDelete = vi.fn();
  render(
    <SecretsTable
      secrets={[edit, read]}
      purposes={PURPOSES}
      onShare={onShare}
      onRotate={noop}
      onDelete={onDelete}
    />,
  );
  expect(screen.getByText("Read-only key")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Rotate Read-only key" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Delete Read-only key" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Delete Granted key" }));
  expect(onDelete).toHaveBeenCalledWith(edit);
  await userEvent.click(screen.getByRole("button", { name: /access.*Granted key/i }));
  expect(onShare).toHaveBeenCalledWith(edit);
});
