import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillGalleryDialog } from "./skill-gallery-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const GALLERY = {
  industries: [
    {
      id: "healthcare",
      skills: [
        {
          key: "healthcare/patient-enquiry-triage",
          name: "Patient enquiry triage",
          description: "Which messages an agent may answer.",
          category: "customer-support",
          installed: false,
        },
        {
          key: "healthcare/consent-explainer",
          name: "Consent explainer",
          description: "Explain a form without advising.",
          category: null,
          installed: true,
        },
      ],
    },
    // An id with no icon in the table, to prove the fallback rather than a
    // blank card.
    { id: "aerospace", skills: [] },
  ],
};

function open() {
  return render(<SkillGalleryDialog open onOpenChange={vi.fn()} />, { wrapper });
}

describe("SkillGalleryDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(GALLERY);
    vi.mocked(apiClient.post).mockResolvedValue({ installed: [], skipped: [], unknown: [] });
  });

  it("does not fetch the gallery until the dialog is open", () => {
    render(<SkillGalleryDialog open={false} onOpenChange={vi.fn()} />, { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("shows a card per industry, and how many are left to install", async () => {
    open();
    expect(await screen.findByText("Healthcare")).toBeInTheDocument();
    // One of the two is already installed, so the card offers one.
    expect(screen.getByText("1 skill")).toBeInTheDocument();
    // An industry with nothing outstanding says so rather than "0 skills".
    expect(screen.getByText("All installed")).toBeInTheDocument();
  });

  it("opens a shelf, and marks what the organization already has", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));

    expect(screen.getByText("Patient enquiry triage")).toBeInTheDocument();
    expect(screen.getByText("Installed")).toBeInTheDocument();
    expect(screen.getByText("customer-support")).toBeInTheDocument();
    // The installed one offers no button; only the outstanding one does.
    expect(screen.getAllByRole("button", { name: "Install" })).toHaveLength(1);
  });

  it("installs one skill by its key", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      installed: ["Patient enquiry triage"],
      skipped: [],
      unknown: [],
    });
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/skills/gallery/install", {
        keys: ["healthcare/patient-enquiry-triage"],
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("1 skill installed");
  });

  it("installs the whole shelf, sending only what is outstanding", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Install 1 skill" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/skills/gallery/install", {
        keys: ["healthcare/patient-enquiry-triage"],
      }),
    );
  });

  it("says so rather than claiming success when everything was already there", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      installed: [],
      skipped: ["Consent explainer"],
      unknown: [],
    });
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() => expect(toast.info).toHaveBeenCalledWith("You already had that skill"));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("surfaces a refusal instead of failing silently", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(403, "Nope", { error: { code: "FORBIDDEN", message: "Nope", details: {} } }),
    );
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("goes back to the shelves", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "All industries" }));
    expect(screen.getByText("Skill gallery")).toBeInTheDocument();
  });

  it("forgets which shelf was open when the dialog closes", async () => {
    const onOpenChange = vi.fn();
    render(<SkillGalleryDialog open onOpenChange={onOpenChange} />, { wrapper });
    await userEvent.click(await screen.findByText("Healthcare"));

    await userEvent.keyboard("{Escape}");

    // The close is reported upward, and the shelf is dropped on the way - so
    // reopening lands on the industries rather than inside the last one.
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(screen.getByText("Skill gallery")).toBeInTheDocument();
  });

  it("shows the install in flight rather than a dead button", async () => {
    let release: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    // The row's own button becomes a spinner; the shelf button is disabled.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Install 1 skill" })).toBeDisabled();
    release({ installed: [], skipped: [], unknown: [] });
  });

  it("renders an error state rather than an empty gallery", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("down"));
    open();

    // The error state itself, not merely the absence of the gallery - which is
    // also what loading looks like.
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Healthcare")).not.toBeInTheDocument();
  });
});
