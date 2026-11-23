import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgCurrency } from "./org-currency";
import type { Organization } from "@/types";

const state = vi.hoisted(() => ({
  allowed: true,
  failed: false,
  saveFailed: false,
  loading: false,
  saving: false,
  mutate: vi.fn(),
  reset: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed }),
}));
const query = vi.fn();
vi.mock("@/hooks/use-currencies", () => ({
  useOrganizationCurrency: (org: string) => {
    query(org);
    return {
      context: {
        isError: state.failed,
        refetch: state.refetch,
        data: state.loading
          ? undefined
          : { default_currency: "PLN", rates: { USD: "1", PLN: "4", EUR: "0.9" } },
      },
      save: {
        isError: state.saveFailed,
        isPending: state.saving,
        mutate: state.mutate,
        reset: state.reset,
      },
    };
  },
}));
const org = { id: "org", currency: null } as Organization;
beforeEach(() => {
  state.allowed = true;
  state.failed = false;
  state.saveFailed = false;
  state.loading = false;
  state.saving = false;
  vi.clearAllMocks();
});

describe("organization currency", () => {
  it("does not load settings or show a control without organization settings permission", () => {
    state.allowed = false;
    render(<OrgCurrency org={org} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(query).not.toHaveBeenCalled();
  });
  it("saves an explicit currency and restores inheritance with null", async () => {
    const user = userEvent.setup();
    const view = render(<OrgCurrency org={org} />);
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "EUR" }));
    expect(state.mutate).toHaveBeenCalledWith("EUR");
    view.rerender(<OrgCurrency org={{ ...org, currency: "EUR" }} />);
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Inherit (PLN)" }));
    expect(state.mutate).toHaveBeenLastCalledWith(null);
    expect(query).toHaveBeenCalledWith("org");
  });
  it("reports a failed read and supports retry", async () => {
    state.failed = true;
    render(<OrgCurrency org={org} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalled();
  });
  it("does not enable a selector without known rates", () => {
    state.loading = true;
    render(<OrgCurrency org={org} />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
  it("reports save failure without claiming success", async () => {
    state.saveFailed = true;
    render(<OrgCurrency org={org} />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be saved");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.reset).toHaveBeenCalled();
  });
});
