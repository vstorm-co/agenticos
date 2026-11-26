import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { listImportDestinations } from "@/lib/portability-api";
import { ImportDestinationPicker } from "./import-destination-picker";
vi.mock("@/lib/portability-api", () => ({ listImportDestinations: vi.fn() }));
function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}
beforeEach(() => vi.resetAllMocks());
function Picker() {
  const [value, setValue] = useState("");
  return (
    <ImportDestinationPicker
      id="pick"
      kind="context"
      value={value}
      disabled={false}
      onChange={setValue}
    />
  );
}

it("searches and pages authorized names without discarding the chosen destination", async () => {
  vi.mocked(listImportDestinations).mockImplementation(async (query) => {
    if (query.search === "error") throw new Error("Permission denied");
    if (query.search) return { items: [], total: 0, searchable: true };
    return {
      items: query.skip === 0 ? [{ id: "alpha", name: "Alpha" }] : [{ id: "beta", name: "Beta" }],
      total: 50,
      searchable: true,
    };
  });
  render(<Picker />, { wrapper: Wrapper });
  await waitFor(() => expect(screen.getByRole("combobox")).toBeEnabled());
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: "Alpha" }));
  await userEvent.click(screen.getByRole("button", { name: "Next resources" }));
  await waitFor(() =>
    expect(listImportDestinations).toHaveBeenCalledWith(expect.objectContaining({ skip: 25 })),
  );
  expect(screen.getByText("Alpha")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Previous resources" }));
  await userEvent.type(screen.getByRole("searchbox"), "missing");
  expect(await screen.findByText("No matching resources.")).toBeVisible();
  await userEvent.clear(screen.getByRole("searchbox"));
  await userEvent.type(screen.getByRole("searchbox"), "error");
  expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied");
});

it("defers known destination inventories until the picker is opened", async () => {
  vi.mocked(listImportDestinations).mockResolvedValue({
    items: [{ id: "current", name: "Current workflow" }],
    total: 1,
    searchable: false,
  });
  render(
    <ImportDestinationPicker
      id="workflow"
      kind="workflow"
      value="current"
      selectedName="Current workflow"
      disabled={false}
      onChange={vi.fn()}
    />,
    { wrapper: Wrapper },
  );
  expect(screen.getByText("Current workflow")).toBeVisible();
  expect(listImportDestinations).not.toHaveBeenCalled();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("combobox"));
  await waitFor(() => expect(listImportDestinations).toHaveBeenCalledTimes(1));
});

it("requires a destination owner before looking up its published versions", () => {
  render(
    <ImportDestinationPicker
      id="version"
      kind="agent_version"
      value=""
      disabled={false}
      onChange={vi.fn()}
    />,
    { wrapper: Wrapper },
  );
  expect(
    screen.getByText(
      "Choose an existing destination agent or Skill first to select its version or fork.",
    ),
  ).toBeVisible();
  expect(listImportDestinations).not.toHaveBeenCalled();
});
