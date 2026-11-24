import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../../messages/en.json";
import type { ToolCall } from "@/types";

import {
  SecretRequestResult,
  parseSecretRequest,
  secretRequestDeclined,
  secretRequestFulfilled,
} from "./secret-request";

function call(result: unknown): ToolCall {
  return {
    id: "c1",
    name: "request_secret",
    status: result === undefined ? "awaiting_answer" : "completed",
    args: {
      secret_name: "acme_api_key",
      what_for: "Acme CRM, to list contacts",
      kind: "api_key",
    },
    result,
  } as unknown as ToolCall;
}

function renderResult(toolCall: ToolCall) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SecretRequestResult
        requested={parseSecretRequest(toolCall)!}
        fulfilled={secretRequestFulfilled(toolCall)}
        declined={secretRequestDeclined(toolCall)}
      />
    </NextIntlClientProvider>,
  );
}

describe("what a request_secret step shows", () => {
  it("reads the name and what it is for from the arguments", () => {
    expect(parseSecretRequest(call(undefined))).toEqual({
      secretName: "acme_api_key",
      whatFor: "Acme CRM, to list contacts",
      kind: "api_key",
    });
  });

  it("is not a secret request when the arguments carry none", () => {
    expect(parseSecretRequest({ ...call({}), args: {} } as ToolCall)).toBeNull();
    expect(parseSecretRequest({ ...call({}), args: { secret_name: "x" } } as ToolCall)).toBeNull();
  });

  it("says the secret is still waited on while the run waits for it", () => {
    renderResult(call(undefined));

    expect(screen.getByText("acme_api_key")).toBeInTheDocument();
    expect(screen.getByText("Acme CRM, to list contacts")).toBeInTheDocument();
    expect(screen.getByText("Waiting for the secret")).toBeInTheDocument();
  });

  it("says the secret was provided once fulfilled, without ever showing a value", () => {
    renderResult(
      call("Secret provided and stored: 'acme_api_key' (hint …9c2f). Continue the work."),
    );

    expect(screen.getByText("Secret provided")).toBeInTheDocument();
    expect(screen.queryByText(/9c2f/)).not.toBeInTheDocument();
  });

  it("says the person declined when the result is a decline", () => {
    renderResult(
      call(
        "The user declined to provide this secret. Do not ask for it again; end with a failed report.",
      ),
    );

    expect(screen.getByText("You declined to provide this secret")).toBeInTheDocument();
  });
});
