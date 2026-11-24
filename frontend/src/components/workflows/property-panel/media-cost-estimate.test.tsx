import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkflowMediaEstimate } from "@/hooks/use-workflow-media-estimate";
import { useWorkflowMediaScope } from "@/hooks/use-workflow-media-scope";
import { apiClient } from "@/lib/api-client";
import type {
  WorkflowMediaEstimateRead,
  WorkflowMediaEstimateRequest,
} from "@/lib/workflows/types";
import { useAuthStore, useOrgStore } from "@/stores";

import { MediaCostEstimate } from "./media-cost-estimate";

vi.mock("@/lib/api-client", () => ({ apiClient: { post: vi.fn() } }));

const USER = {
  id: "account-a",
  email: "a@example.invalid",
  is_active: true,
  created_at: "2026-11-16T00:00:00Z",
};
const REQUEST: WorkflowMediaEstimateRequest = {
  kind: "image",
  config: {
    provider: "openai",
    model: "gpt-image-1.5",
    secret_id: "key-a",
    quality: "high",
    max_cost_usd: 1,
  },
};
const ESTIMATE: WorkflowMediaEstimateRead = {
  kind: "image",
  provider: "openai",
  model: "gpt-image-1.5",
  reservation_usd: "0.42",
  reserved_bytes: 33_554_432,
  pricing_as_of: "2026-11-16",
  configured_max_cost_usd: "1",
  sufficient_max_cost_usd: true,
  deficit_usd: "0",
  assumptions: [
    { code: "conservative_reservation" },
    { code: "single_submission" },
    { code: "dispatch_limits_rechecked" },
    { code: "unresolved_hold_retained" },
    { code: "text_only" },
    { code: "image_token_ceiling", max_input_tokens: 100, max_output_tokens: 200 },
    {
      code: "image_tool_ceiling",
      prompt_max_characters: 16000,
      quality: "high",
      size: "1024x1024",
      output_estimate_usd: "0.10",
      output_ceiling_usd: "0.11",
    },
  ],
};
const clients: QueryClient[] = [];

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return function EstimateProvider({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function pending() {
  let resolve!: (value: WorkflowMediaEstimateRead) => void;
  const promise = new Promise<WorkflowMediaEstimateRead>((done) => {
    resolve = done;
  });
  vi.mocked(apiClient.post).mockReturnValueOnce(promise);
  return { resolve };
}

const calculate = () =>
  userEvent.click(screen.getByRole("button", { name: "Estimate reservation" }));

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({
    user: USER,
    sessionOwnerId: USER.id,
    isAuthenticated: true,
    impersonationRevoked: false,
  });
  useOrgStore.setState({ activeOrgId: "org-a", refusedOrgIds: [] });
  vi.mocked(apiClient.post).mockResolvedValue(ESTIMATE);
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});

describe("media reservation estimate", () => {
  it("calculates only on request and renders the server's amount and closed assumptions", async () => {
    render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(
      screen.getByText("This calculation does not contact the provider or generate media."),
    ).toBeInTheDocument();
    await calculate();
    expect(await screen.findByText("Estimated reservation: $0.42")).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith("/workflows/media-estimate", REQUEST, {
      signal: expect.any(AbortSignal),
      cache: "no-store",
    });
    expect(screen.getByText("Storage reservation: 32.0 MB")).toBeInTheDocument();
    expect(screen.getByText("Configured maximum cost: $1.00")).toBeInTheDocument();
    await userEvent.click(screen.getByText("How this is estimated"));
    expect(
      screen.getByText("The reservation is a conservative bound; the final charge can be lower."),
    ).toBeVisible();
    expect(screen.getByText("The estimate covers one provider submission.")).toBeVisible();
    expect(
      screen.getByText(
        "Current permissions, budgets and storage limits are checked again before sending.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Unresolved charges stay reserved until they can be reconciled."),
    ).toBeVisible();
    expect(screen.getByText("This workflow model accepts text prompts only.")).toBeVisible();
    expect(
      screen.getByText("Reserved token limits: 100 input and 200 output tokens."),
    ).toBeVisible();
    expect(
      screen.getByText(/output is estimated at \$0.10 with a ceiling of \$0.11/),
    ).toBeVisible();
  });

  it.each([true, false])(
    "describes duration-based pricing with maximum/sound flags %s",
    async (maximum) => {
      const request: WorkflowMediaEstimateRequest = {
        kind: "video",
        config: { provider: "google", model: "video-model", secret_id: "key-v" },
      };
      vi.mocked(apiClient.post).mockResolvedValue({
        ...ESTIMATE,
        kind: "video",
        assumptions: [
          {
            code: "video_duration_rate",
            seconds: 8,
            resolution: "720p",
            usd_per_second: "0.20",
            uses_model_maximum: maximum,
            sound_on_ceiling: maximum,
          },
        ],
      });
      render(<MediaCostEstimate request={request} />, { wrapper: wrapper() });
      await calculate();
      await screen.findByText("Estimated reservation: $0.42");
      expect(
        screen.getByText(/8 seconds at 720p, priced at \$0.20 per second/),
      ).toBeInTheDocument();
      expect(Boolean(screen.queryByText(/maximum duration is reserved/))).toBe(maximum);
      expect(Boolean(screen.queryByText(/includes the sound-on rate/))).toBe(maximum);
    },
  );

  it.each([
    [null, "Set a maximum cost of at least $0.42 before running."],
    ["0.12", "The maximum cost is short by $0.30."],
  ])(
    "explains an insufficient maximum of %s using the server deficit",
    async (maximum, message) => {
      vi.mocked(apiClient.post).mockResolvedValue({
        ...ESTIMATE,
        configured_max_cost_usd: maximum,
        sufficient_max_cost_usd: false,
        deficit_usd: "0.30",
      });
      render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
      await calculate();
      expect(await screen.findByRole("alert")).toHaveTextContent(message as string);
    },
  );

  it.each([undefined, null, "", "   "])(
    "cannot calculate without a selected provider key (%s)",
    async (secret_id) => {
      render(
        <MediaCostEstimate request={{ ...REQUEST, config: { ...REQUEST.config, secret_id } }} />,
        { wrapper: wrapper() },
      );
      expect(screen.getByRole("button", { name: "Estimate reservation" })).toBeDisabled();
      expect(
        screen.getByText("Choose a provider API key to calculate the reservation."),
      ).toBeInTheDocument();
      await calculate();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("respects the catalog/form's disabled state", async () => {
    render(<MediaCostEstimate request={REQUEST} disabled />, { wrapper: wrapper() });
    await calculate();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("removes a previous estimate immediately when any setting changes", async () => {
    const view = render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
    await calculate();
    await screen.findByText("Estimated reservation: $0.42");
    view.rerender(
      <MediaCostEstimate request={{ ...REQUEST, config: { ...REQUEST.config, quality: "low" } }} />,
    );
    expect(screen.queryByText("Estimated reservation: $0.42")).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it("aborts and ignores a late response for earlier settings", async () => {
    const old = pending();
    const view = render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
    await calculate();
    expect(screen.getByRole("button", { name: "Calculating…" })).toBeDisabled();
    const signal = vi.mocked(apiClient.post).mock.calls[0]?.[2]?.signal;
    view.rerender(
      <MediaCostEstimate
        request={{ ...REQUEST, config: { ...REQUEST.config, secret_id: "key-b" } }}
      />,
    );
    expect(signal?.aborted).toBe(true);
    await act(async () => old.resolve(ESTIMATE));
    expect(screen.queryByText("Estimated reservation: $0.42")).toBeNull();
    await calculate();
    expect(await screen.findByText("Estimated reservation: $0.42")).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["organization", () => useOrgStore.setState({ activeOrgId: "org-b" })],
    [
      "account",
      () =>
        useAuthStore.setState({ user: { ...USER, id: "account-b" }, sessionOwnerId: "account-b" }),
    ],
    ["refused organization", () => useOrgStore.setState({ refusedOrgIds: ["org-a"] })],
    ["sign-out", () => useAuthStore.setState({ user: null, isAuthenticated: false })],
  ] as const)("discards pending private estimates on %s change", async (_label, change) => {
    const old = pending();
    render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
    await calculate();
    const signal = vi.mocked(apiClient.post).mock.calls[0]?.[2]?.signal;
    act(change);
    expect(signal?.aborted).toBe(true);
    await act(async () => old.resolve(ESTIMATE));
    expect(screen.queryByText("Estimated reservation: $0.42")).toBeNull();
  });

  it.each([new Error("key is not available"), new Error(), "unavailable"])(
    "shows a calculation refusal without retrying it (%s)",
    async (error) => {
      vi.mocked(apiClient.post).mockRejectedValue(error);
      render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
      await calculate();
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(
        error instanceof Error && error.message
          ? error.message
          : "The estimate could not be calculated.",
      );
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("Estimated reservation: $0.42")).toBeNull();
    },
  );

  it("allows a deliberate new calculation after a refusal", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error());
    render(<MediaCostEstimate request={REQUEST} />, { wrapper: wrapper() });
    await calculate();
    await screen.findByRole("alert");
    await calculate();
    await screen.findByText("Estimated reservation: $0.42");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("estimate request identity fence", () => {
  function useEstimate() {
    const scope = useWorkflowMediaScope();
    return useWorkflowMediaEstimate(REQUEST, scope);
  }

  it("refuses a stale callback before it can issue the request", async () => {
    const { result } = renderHook(useEstimate, { wrapper: wrapper() });
    act(() => useAuthStore.setState({ isAuthenticated: false }));
    await act(async () => {
      await expect(result.current.mutateAsync()).rejects.toThrow();
    });
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("also rechecks identity after a completed server calculation", async () => {
    const old = pending();
    const { result } = renderHook(useEstimate, { wrapper: wrapper() });
    let request!: Promise<WorkflowMediaEstimateRead>;
    act(() => {
      request = result.current.mutateAsync();
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await act(async () => {
      old.resolve(ESTIMATE);
      await expect(request).rejects.toThrow();
    });
  });
});
