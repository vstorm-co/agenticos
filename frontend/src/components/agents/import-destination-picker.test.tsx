import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { listImportDestinations, type ImportDestinationList } from "@/lib/portability-api";
import { ImportDestinationPicker } from "./import-destination-picker";

vi.mock("@/lib/portability-api", () => ({ listImportDestinations: vi.fn() }));
const onChange = vi.fn();
const props = { id: "destination", kind: "context", value: "", disabled: false, onChange };
function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listImportDestinations).mockResolvedValue({
    items: [{ id: "policy", name: "Policy" }],
    total: 1,
    searchable: true,
  });
});

it("waits for the destination owner before listing a version", async () => {
  const view = render(<ImportDestinationPicker {...props} kind="skill_version" />, {
    wrapper: Wrapper,
  });
  expect(screen.getByText(/Choose an existing destination agent or Skill first/)).toBeVisible();
  expect(listImportDestinations).not.toHaveBeenCalled();
  view.rerender(
    <ImportDestinationPicker {...props} kind="skill_version" parentId="destination-skill" />,
  );
  await waitFor(() =>
    expect(listImportDestinations).toHaveBeenCalledWith(
      expect.objectContaining({ parent_id: "destination-skill" }),
    ),
  );
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
});

it("lists actual authorized names and returns a selected identity", async () => {
  render(<ImportDestinationPicker {...props} />, { wrapper: Wrapper });
  await waitFor(() => expect(screen.getByRole("combobox")).toBeEnabled());
  await userEvent.click(screen.getByRole("combobox", { name: "Destination resource" }));
  await userEvent.click(await screen.findByRole("option", { name: "Policy" }));
  expect(onChange).toHaveBeenCalledWith("policy");
});

it("retains a selected destination across searches and resets the page", async () => {
  vi.mocked(listImportDestinations).mockResolvedValue({ items: [], total: 60, searchable: true });
  render(<ImportDestinationPicker {...props} value="chosen" selectedName="Chosen destination" />, {
    wrapper: Wrapper,
  });
  expect(await screen.findByText("No matching resources.")).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveTextContent("Chosen destination");
  await userEvent.click(screen.getByRole("button", { name: "Next resources" }));
  await waitFor(() =>
    expect(listImportDestinations).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 25 })),
  );
  await userEvent.click(screen.getByRole("button", { name: "Previous resources" }));
  await waitFor(() =>
    expect(listImportDestinations).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 0 })),
  );
  fireEvent.change(screen.getByRole("searchbox", { name: "Search resources" }), {
    target: { value: "Policy" },
  });
  await waitFor(() =>
    expect(listImportDestinations).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: "Policy", skip: 0 }),
    ),
  );
});

it("distinguishes loading and refusal from an empty catalog", async () => {
  const request = Promise.withResolvers<ImportDestinationList>();
  vi.mocked(listImportDestinations).mockReturnValue(request.promise);
  render(<ImportDestinationPicker {...props} value="known" />, { wrapper: Wrapper });
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.queryByText("No matching resources.")).not.toBeInTheDocument();
  request.reject(new Error("Destination access revoked"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Destination access revoked");
  expect(screen.getByRole("combobox")).toHaveTextContent("Selected resource");
});
