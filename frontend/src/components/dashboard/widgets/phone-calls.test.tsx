import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PhoneCallsWidget } from "./phone-calls";
import { phoneCall } from "@/test-utils/phone";
const state = vi.hoisted(() => ({ loading: false, calls: [] as { id: string }[], retry: vi.fn() }));
vi.mock("@/hooks/use-phone", () => ({
  usePhoneCalls: () => ({
    isLoading: state.loading,
    error: null,
    data: state.calls,
    refetch: state.retry,
  }),
}));
vi.mock("@/components/phone/phone-call-card", () => ({
  PhoneReceiptCard: ({ call }: { call: { id: string } }) => <p>{call.id}</p>,
}));
const props = {
  title: "Phone calls",
  hint: "",
  period: { preset: "30d" as const, from: "2026-10-01", to: "2026-10-31" },
};
it("limits the dashboard to three receipts without dialing", () => {
  state.calls = Array.from({ length: 4 }, (_, i) => ({ ...phoneCall, id: `receipt-${i}` }));
  render(<PhoneCallsWidget {...props} />);
  expect(screen.getByText("receipt-2")).toBeVisible();
  expect(screen.queryByText("receipt-3")).not.toBeInTheDocument();
});
