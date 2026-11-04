import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { phoneApi } from "@/lib/phone-api";
import { phoneCall } from "@/test-utils/phone";
import { PhoneCallCard, PhoneReceiptCard } from "./phone-call-card";
vi.mock("@/lib/phone-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/phone-api")>()),
  phoneApi: { hangup: vi.fn(), transfer: vi.fn(), transferOptions: vi.fn() },
}));
vi.mock("@/hooks/use-phone", () => ({
  usePhoneCall: () => ({ data: undefined, error: new Error("Not yours"), isLoading: false }),
}));
beforeEach(() => {
  vi.mocked(phoneApi.hangup).mockReset();
});
function mount(call = phoneCall) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
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
