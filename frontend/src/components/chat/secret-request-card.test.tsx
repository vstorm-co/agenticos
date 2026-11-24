import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import type { ParkedSecretRequest } from "@/types/runs";

import { SecretRequestCard } from "./secret-request-card";

const REQUESTS: ParkedSecretRequest[] = [
  {
    id: "req-1",
    run_id: "run-1",
    tool_call_id: "call-1",
    secret_name: "acme_api_key",
    kind: "api_key",
    what_for: "Acme CRM, to list contacts",
    status: "pending",
  },
];

function renderCard(props: Partial<React.ComponentProps<typeof SecretRequestCard>> = {}) {
  const onSubmit = vi.fn();
  const onDecline = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SecretRequestCard requests={REQUESTS} onSubmit={onSubmit} onDecline={onDecline} {...props} />
    </NextIntlClientProvider>,
  );
  return { onSubmit, onDecline };
}

describe("the secret request card", () => {
  it("names the secret and what it is for, with a password input", () => {
    renderCard();

    expect(screen.getByText("acme_api_key")).toBeInTheDocument();
    expect(screen.getByText("Acme CRM, to list contacts")).toBeInTheDocument();
    expect(screen.getByLabelText("Secret value")).toHaveAttribute("type", "password");
  });

  it("does not let an empty value be provided", () => {
    const { onSubmit } = renderCard();

    expect(screen.getByRole("button", { name: "Provide secret" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Provide secret" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the typed value and clears the input", () => {
    const { onSubmit } = renderCard();
    const input = screen.getByLabelText("Secret value");

    fireEvent.change(input, { target: { value: "sk-test-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Provide secret" }));

    expect(onSubmit).toHaveBeenCalledWith("req-1", "sk-test-value");
    expect(input).toHaveValue("");
  });

  it("declines the request", () => {
    const { onDecline } = renderCard();

    fireEvent.click(screen.getByRole("button", { name: "Decline" }));

    expect(onDecline).toHaveBeenCalledWith("req-1");
  });

  it("renders nothing with no requests", () => {
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <SecretRequestCard requests={[]} onSubmit={vi.fn()} onDecline={vi.fn()} />
      </NextIntlClientProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
