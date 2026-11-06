import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { phoneApi } from "@/lib/phone-api";
import { phoneCall } from "@/test-utils/phone";
import { PhoneCallCard, PhoneReceiptCard } from "./phone-call-card";
vi.mock("@/lib/phone-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/phone-api")>()),
  phoneApi: { hangup: vi.fn(), transfer: vi.fn(), transferOptions: vi.fn() },
}));
const receipt = vi.hoisted(() => {
  const state: {
    data?: import("@/lib/phone-api").PhoneCall;
    error: Error | null;
    isLoading: boolean;
  } = { error: null, isLoading: false };
  return state;
});
vi.mock("@/hooks/use-phone", () => ({ usePhoneCall: () => receipt }));
beforeEach(() => {
  vi.mocked(phoneApi.hangup).mockReset();
  vi.mocked(phoneApi.transfer).mockReset();
  vi.mocked(phoneApi.transferOptions).mockReset();
  receipt.data = undefined;
  receipt.error = new Error("Not yours");
  receipt.isLoading = false;
});
function mount(call = phoneCall) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PhoneReceiptCard call={call} />
    </QueryClientProvider>,
  );
}
it("does not describe unknown acceptance as successful and can stop the intent", async () => {
  vi.mocked(phoneApi.hangup).mockResolvedValue();
  mount();
  expect(screen.getByText("Awaiting provider confirmation")).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "End call" }));
  await waitFor(() => expect(phoneApi.hangup).toHaveBeenCalledWith("call"));
});
it("links an ended conversation to its transcript and offers no new effect", () => {
  mount({ ...phoneCall, status: "completed", conversation_id: "conversation" });
  expect(screen.getByRole("link", { name: "Open transcript" })).toHaveAttribute(
    "href",
    "/chat?id=conversation",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("does not expose an inaccessible receipt", () => {
  render(<PhoneCallCard callId="foreign" />);
  expect(screen.getByText("This call receipt is unavailable to you.")).toBeVisible();
});

it("previews a delayed report without presenting it as a completed telephone conversation", () => {
  mount({
    ...phoneCall,
    status: "queued",
    mode: "report",
    conversation_id: "report",
    not_before: "2026-11-05T10:00:00Z",
  });
  expect(screen.getByRole("link", { name: "Prepared report" })).toHaveAttribute(
    "href",
    "/chat?id=report",
  );
  expect(screen.getByText(/Earliest call/)).toBeVisible();
});
it("offers only current transfer contacts and closes after confirmed transfer", async () => {
  vi.mocked(phoneApi.transferOptions).mockResolvedValue([
    { id: "person", label: "On-call person" },
  ]);
  vi.mocked(phoneApi.transfer).mockResolvedValue();
  mount({ ...phoneCall, status: "active" });
  await userEvent.click(screen.getByRole("button", { name: "Transfer call" }));
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "On-call person" }));
  await userEvent.click(screen.getAllByRole("button", { name: "Transfer call" }).at(-1)!);
  await waitFor(() => expect(phoneApi.transfer).toHaveBeenCalledWith("call", "person"));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("keeps a failed stop visible and explains the refusal", async () => {
  const error = vi.spyOn(toast, "error");
  vi.mocked(phoneApi.hangup).mockRejectedValue(new Error("Could not stop the call"));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "End call" }));
  await waitFor(() => expect(error).toHaveBeenCalled());
  expect(screen.getByRole("button", { name: "End call" })).toBeEnabled();
});
it("shows a loading receipt and then the current saved receipt", () => {
  receipt.isLoading = true;
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <PhoneCallCard callId="call" />
    </QueryClientProvider>,
  );
  expect(screen.getByText(/Loading/)).toBeVisible();
  receipt.isLoading = false;
  receipt.error = null;
  receipt.data = { ...phoneCall, status: "completed" };
  view.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <PhoneCallCard callId="call" />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Ended")).toBeVisible();
});
it("can dismiss the transfer picker without placing a transfer", async () => {
  vi.mocked(phoneApi.transferOptions).mockResolvedValue([]);
  mount({ ...phoneCall, status: "active" });
  await userEvent.click(screen.getByRole("button", { name: "Transfer call" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(phoneApi.transfer).not.toHaveBeenCalled();
});
it("keeps the selected contact after a refused transfer", async () => {
  const error = vi.spyOn(toast, "error");
  vi.mocked(phoneApi.transferOptions).mockResolvedValue([
    { id: "person", label: "On-call person" },
  ]);
  vi.mocked(phoneApi.transfer).mockRejectedValue(new Error("Transfer unavailable"));
  mount({ ...phoneCall, status: "active" });
  await userEvent.click(screen.getByRole("button", { name: "Transfer call" }));
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "On-call person" }));
  await userEvent.click(screen.getAllByRole("button", { name: "Transfer call" }).at(-1)!);
  await waitFor(() => expect(error).toHaveBeenCalled());
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveTextContent("On-call person");
});
