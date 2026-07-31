import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CustomIconsProvider, CustomMark, useCustomIcons } from "./custom-icons";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn() } };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function Probe() {
  const icons = useCustomIcons();
  return <output>{[...icons].join(",")}</output>;
}

describe("CustomIconsProvider", () => {
  it("distributes the deployment's icon names to whoever asks", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: ["acme", "initech"], total: 2 });

    render(
      <CustomIconsProvider>
        <Probe />
      </CustomIconsProvider>,
      { wrapper },
    );

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("acme,initech"));
  });

  it("hands an empty set to a component mounted outside it", () => {
    // The default matters: the icon components render in unit tests and
    // storybooks with no provider above them, and "no custom icons" must be
    // a working answer there, not a crash.
    render(<Probe />);
    expect(screen.getByRole("status")).toHaveTextContent("");
  });
});

describe("CustomMark", () => {
  it("draws the icon as a currentColor mask, not as an image", () => {
    // The mask is what makes monochromy structural: whatever colours the
    // operator's SVG holds, what renders is this element's background.
    const { container } = render(<CustomMark name="acme" className="h-5 w-5" />);
    const mark = container.firstElementChild as HTMLElement;

    expect(mark.tagName).not.toBe("IMG");
    expect(mark.style.maskImage).toBe('url("/api/catalog/icons/acme")');
    expect(mark.style.backgroundColor).toBe("currentcolor");
    expect(mark).toHaveAttribute("aria-hidden");
  });
});
