import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { KnowledgeFreshnessWidget } from "./knowledge-freshness";

const useSyncSourcesMock = vi.fn();
vi.mock("@/hooks", () => ({ useSyncSources: () => useSyncSourcesMock() }));

it.each(["error", "done"])("presents the worker's %s sync status", (status) => {
  useSyncSourcesMock.mockReturnValue({
    sources: [
      {
        id: "source-1",
        name: "Handbook",
        last_sync_status: status,
        last_error: status === "error" ? "The source could not be reached" : null,
        last_sync_at: "2026-11-01T00:00:00Z",
      },
    ],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <KnowledgeFreshnessWidget
        title="Knowledge sync"
        hint=""
        period={{ preset: "30d", from: "2026-10-10", to: "2026-11-09" }}
      />
    </NextIntlClientProvider>,
  );
  const labels = messages.dashboard.widgets["knowledge-freshness"];
  expect(screen.getByText(status === "error" ? labels.failing : labels.fresh)).toBeInTheDocument();
  if (status === "error") {
    expect(screen.getByText("The source could not be reached")).toBeInTheDocument();
    expect(screen.queryByText(labels.fresh)).not.toBeInTheDocument();
  }
});
