import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WebhookTestCapture, WebhookTestListening } from "@/lib/workflows/types";

import { WebhookListener } from "./webhook-listener";

const mutate = vi.fn();
const stop = vi.fn();
const state: {
  listening: WebhookTestListening | null;
  capture: WebhookTestCapture | null;
} = { listening: null, capture: null };
vi.mock("@/hooks", () => ({
  useWebhookTest: () => ({ ...state, listen: { mutate, isPending: false }, stop }),
}));

const LISTENING = {
  test_token: "tok",
  url: "https://x/api/v1/workflow-webhook-tests/tok",
  expires_at: "",
};

beforeEach(() => {
  vi.clearAllMocks();
  state.listening = null;
  state.capture = null;
});

describe("WebhookListener", () => {
  it("opens a test URL on request", async () => {
    render(<WebhookListener workflowId="wf" onCaught={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Listen for test event" }));
    expect(mutate).toHaveBeenCalled();
  });

  it("shows the URL while it waits, and stops on request", async () => {
    state.listening = LISTENING;
    state.capture = { state: "listening", delivery: null };
    render(<WebhookListener workflowId="wf" onCaught={vi.fn()} />);
    expect(screen.getByText("Waiting for a call")).toBeTruthy();
    expect(screen.getByLabelText("Test URL")).toHaveValue(LISTENING.url);
    await userEvent.click(screen.getByRole("button", { name: "Stop listening" }));
    expect(stop).toHaveBeenCalled();
  });

  it("says when the URL closed with no call, and listens again", async () => {
    state.listening = LISTENING;
    state.capture = { state: "expired", delivery: null };
    render(<WebhookListener workflowId="wf" onCaught={vi.fn()} />);
    expect(screen.getByText("No call arrived in time.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Listen for test event" }));
    expect(mutate).toHaveBeenCalled();
  });

  it("hands the call on once it has come, and stops listening", () => {
    const onCaught = vi.fn();
    const delivery = { body: { lead: 1 }, delivery_id: "t-1" };
    state.listening = LISTENING;
    state.capture = { state: "caught", delivery };
    render(<WebhookListener workflowId="wf" onCaught={onCaught} />);
    expect(onCaught).toHaveBeenCalledWith(delivery);
    expect(stop).toHaveBeenCalled();
  });
});
