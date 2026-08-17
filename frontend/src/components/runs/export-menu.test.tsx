import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportMenu } from "./export-menu";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import { usePermissions } from "@/hooks";
import { toast } from "sonner";

/**
 * The download control that sits on each Activity tab.
 *
 * The two properties worth proving: it is absent - not disabled - without the
 * permission its tab is gated on, and the request it makes carries the tab's
 * current filters plus the page's window, because the backend refuses a range
 * that is missing and caps one that is too wide. A refusal comes back as a toast
 * rather than an empty file, so the wide-range case is said out loud.
 */

vi.mock("@/hooks", () => ({ usePermissions: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { raw: vi.fn() } }));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function grant(...permissions: string[]) {
  vi.mocked(usePermissions).mockReturnValue({
    can: (permission: string) => permissions.includes(permission),
  } as unknown as ReturnType<typeof usePermissions>);
}

function respondWith(disposition: string | null) {
  vi.mocked(apiClient.raw).mockResolvedValue({
    blob: async () => new Blob(["run_id\n"], { type: "text/csv" }),
    headers: { get: (name: string) => (name === "content-disposition" ? disposition : null) },
  } as unknown as Response);
}

function lastExportParams(): Record<string, string> {
  const call = vi.mocked(apiClient.raw).mock.calls.at(-1);
  if (call === undefined) throw new Error("apiClient.raw was not called");
  return (call[1] as { params: Record<string, string> }).params;
}

beforeEach(() => {
  vi.mocked(apiClient.raw).mockReset();
  vi.mocked(saveBlob).mockReset();
  vi.mocked(toast.error).mockReset();
});

const RUNS_PROPS = {
  permission: "runs:view",
  endpoint: "/runs/export",
  kind: "runs",
  rangeParams: { from: "started_from", to: "started_to" },
  range: { from: "2026-07-16T00:00:00.000Z", to: "2026-08-14T23:59:59.999Z" },
} as const;

describe("the export control's permission gate", () => {
  it("is absent for a caller without the permission", () => {
    grant();
    const { container } = render(<ExportMenu {...RUNS_PROPS} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is present for a caller who holds it", () => {
    grant("runs:view");
    render(<ExportMenu {...RUNS_PROPS} />);
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeVisible();
  });
});

describe("the download it makes", () => {
  it("sends the current filters and the page's window, and saves the file", async () => {
    grant("runs:view");
    respondWith('attachment; filename="runs_export_20260810_120000.csv"');

    render(
      <ExportMenu {...RUNS_PROPS} params={{ agent_id: "a-1", include_delegations: "true" }} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(apiClient.raw).toHaveBeenCalledTimes(1));
    expect(vi.mocked(apiClient.raw).mock.calls.at(-1)?.[0]).toBe("/runs/export");
    const params = lastExportParams();
    // The filters travel verbatim.
    expect(params.agent_id).toBe("a-1");
    expect(params.include_delegations).toBe("true");
    // The window is the page's, under the endpoint's own parameter names - the
    // endpoint refuses a request without one.
    expect(params.started_from).toBe("2026-07-16T00:00:00.000Z");
    expect(params.started_to).toBe("2026-08-14T23:59:59.999Z");
    // The server's own filename is honoured.
    await waitFor(() =>
      expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "runs_export_20260810_120000.csv"),
    );
  });

  it("falls back to a kind-based filename when the server sends none", async () => {
    grant("runs:view");
    respondWith(null);

    render(<ExportMenu {...RUNS_PROPS} />);
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "runs_export.csv"));
    // No filters were passed, so only the window is on the request.
    expect(Object.keys(lastExportParams()).sort()).toEqual(["started_from", "started_to"]);
  });

  it("surfaces a refusal as a toast rather than an empty download", async () => {
    grant("runs:view");
    vi.mocked(apiClient.raw).mockRejectedValue(new Error("matched too many rows"));

    render(<ExportMenu {...RUNS_PROPS} />);
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("matched too many rows"));
    expect(saveBlob).not.toHaveBeenCalled();
  });
});
