import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { PublicArtifact } from "./public-artifact";
import type { OpenPublicArtifact } from "@/types/artifact";

const { unlock } = vi.hoisted(() => ({ unlock: vi.fn() }));
vi.mock("@/hooks/use-artifacts", () => ({ usePublicArtifactUnlock: unlock }));
vi.mock("@/components/artifacts/artifact-frame", () => ({
  ArtifactFrameView: () => <div data-testid="frame" />,
}));

const artifact: OpenPublicArtifact = {
  password_required: false,
  title: "Report",
  published_at: "2026-11-10T15:00:00Z",
  view: {
    url: "https://content.example/api/v1/artifact-content/token",
    nonce: "nonce",
    live: false,
    injected: false,
    awaiting_consent: false,
    bindings: 0,
    expires_at: "2026-11-12T00:00:00Z",
    actions_enabled: false,
    actions: [],
    version: {
      id: "v1",
      number: 1,
      media_type: "text/html",
      size_bytes: 10,
      run_id: null,
      restored_from: null,
      consent_state: "not_needed",
      created_at: "2026-11-10T15:00:00Z",
    },
  },
};

beforeEach(() =>
  unlock.mockReturnValue({ data: undefined, error: null, isPending: false, mutate: vi.fn() }),
);

it("applies the server preference to an opened app", () => {
  const { rerender } = render(<PublicArtifact artifact={artifact} publicKey="key" />);
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://github.com/vstorm-co/agenticos",
  );
  rerender(
    <PublicArtifact
      artifact={{ ...artifact, show_agenticos_attribution: false }}
      publicKey="key"
    />,
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByTestId("frame")).toBeInTheDocument();
});

it("waits until a password-protected page is unlocked before showing branding", () => {
  const locked = { password_required: true, title: null, published_at: null, view: null } as const;
  const { rerender } = render(<PublicArtifact artifact={locked} publicKey="key" />);
  expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  unlock.mockReturnValue({ data: artifact });
  rerender(<PublicArtifact artifact={locked} publicKey="key" />);
  expect(screen.getByRole("contentinfo")).toBeVisible();
});
