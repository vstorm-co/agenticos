import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { livePolling } from "@/lib/live-polling";
import { StaleReadBanner } from "./stale-read-banner";

let client: QueryClient;

function LiveRun({ read }: { read: () => Promise<{ status: string }> }) {
  useQuery({
    queryKey: ["run"],
    queryFn: read,
    ...livePolling(60_000, (run: { status: string } | undefined) => run?.status === "running"),
  });
  return null;
}

function page(children: ReactNode) {
  return render(
    <QueryClientProvider client={client}>
      <StaleReadBanner />
      {children}
    </QueryClientProvider>,
  );
}

async function readAgain() {
  const query = await waitFor(() => {
    const found = client.getQueryCache().find({ queryKey: ["run"] });
    expect(found?.state.status).toBe("success");
    return found!;
  });
  await act(() => query.fetch().catch(() => undefined));
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

it("says nothing while every live read answers", async () => {
  page(<LiveRun read={() => Promise.resolve({ status: "running" })} />);
  await readAgain();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("says part of the page stopped updating and why, and reads it again", async () => {
  const read = vi
    .fn<() => Promise<{ status: string }>>()
    .mockResolvedValueOnce({ status: "running" })
    .mockRejectedValueOnce(
      new ApiError(502, "Bad gateway", { error: { code: "BAD_GATEWAY", message: "Bad gateway" } }),
    )
    .mockResolvedValue({ status: "running" });
  page(<LiveRun read={read} />);
  await readAgain();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Part of this page stopped updating and may be out of date. Bad gateway",
  );
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(read).toHaveBeenCalledTimes(3);
});

it("goes once the page that stopped is left", async () => {
  const read = vi
    .fn<() => Promise<{ status: string }>>()
    .mockResolvedValueOnce({ status: "running" })
    .mockRejectedValue(new Error("refused"));
  const view = page(<LiveRun read={read} />);
  await readAgain();
  expect(await screen.findByRole("alert")).toBeInTheDocument();

  view.rerender(
    <QueryClientProvider client={client}>
      <StaleReadBanner />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});
