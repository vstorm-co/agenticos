import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UploadOverrideDialog } from "./upload-override-dialog";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";

/**
 * What the next files added to a collection carry, decided before they arrive.
 *
 * Two things now, not one: how they are read, and which part of the
 * organization they belong to. The second is here for the same reason the
 * first is - a file arrives three ways, all three have to carry the decision,
 * and a form that owned the upload would cover one of them (#1777).
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

function open(props: Partial<Parameters<typeof UploadOverrideDialog>[0]> = {}) {
  const onApply = vi.fn();
  render(
    <Wrapper>
      <UploadOverrideDialog
        open
        onOpenChange={vi.fn()}
        config={DEFAULT_INGESTION_CONFIG}
        override={{}}
        organizationalUnit=""
        onApply={onApply}
        {...props}
      />
    </Wrapper>,
  );
  return onApply;
}

describe("the organizational unit the next uploads are filed under", () => {
  it("reaches the caller, trimmed, when the dialog is applied", async () => {
    const onApply = open();

    await userEvent.type(screen.getByLabelText("Organizational unit"), "  Legal  ");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledWith({}, "Legal");
  });

  it("opens on the unit already in force rather than empty", async () => {
    open({ organizationalUnit: "Legal" });

    expect(screen.getByLabelText("Organizational unit")).toHaveValue("Legal");
  });

  it("survives the button that goes back to the collection's parse settings", async () => {
    // That button says what it does - it is about how a file is read. The unit
    // is not one of the collection's settings, and dropping what was just typed
    // would be a second change nobody asked for.
    const onApply = open({ override: { ocr: true } });

    await userEvent.type(screen.getByLabelText("Organizational unit"), "Legal");
    await userEvent.click(screen.getByRole("button", { name: "Use the collection's settings" }));

    expect(onApply).toHaveBeenCalledWith({}, "Legal");
  });

  it("does not make the apply button claim nothing changed", async () => {
    // The count on that button is of parse departures, so a dialog closed after
    // naming only a unit used to read "Nothing changed" over a change it was
    // about to make.
    open();

    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });
});
