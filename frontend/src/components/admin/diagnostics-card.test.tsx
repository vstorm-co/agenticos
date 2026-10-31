import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { DiagnosticsCard } from "./diagnostics-card";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
afterEach(() => vi.clearAllMocks());
const status = {
  enabled: true,
  collector: "https://analytics-agenticos.testapp.ovh",
  instance_id: null,
  last_attempt: null,
  last_success: null,
  last_error: null,
};
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DiagnosticsCard />
    </QueryClientProvider>,
  );
}
it("shows delivery status without exposing the collector address", async () => {
  vi.mocked(apiClient.get).mockResolvedValue(status);
  mount();
  expect(screen.getByText("loading")).toBeInTheDocument();
  expect(await screen.findByText("enabled")).toBeInTheDocument();
  expect(screen.getByText("never")).toBeInTheDocument();
  expect(screen.queryByText(status.collector)).not.toBeInTheDocument();
  expect(screen.getByText("DIAGNOSTICS_ENABLED=false")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "refresh" }));
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
});
it("shows explicit opt-out and the last delivery outcome", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({
    ...status,
    enabled: false,
    last_success: 1,
    last_error: "transport",
  });
  mount();
  expect(await screen.findByText("disabled")).toBeInTheDocument();
  expect(screen.getByText("transport")).toBeInTheDocument();
  expect(screen.queryByText("never")).not.toBeInTheDocument();
});
it("keeps unavailable status distinct from disabled reporting", async () => {
  vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
  mount();
  expect(await screen.findByText("unavailable")).toBeInTheDocument();
  expect(screen.queryByText("disabled")).not.toBeInTheDocument();
});
