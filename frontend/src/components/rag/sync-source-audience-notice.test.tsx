import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourceAudienceNotice } from "./sync-source-audience-notice";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const CREDENTIAL = {
  id: "secret-1",
  name: "Drive service account",
  kind: "gcp_service_account",
  purpose: "custom",
  hint: "a1b2",
  visibility: "org",
  created_at: "2026-08-20T00:00:00Z",
};

/** The notice reads the vault itself, so the vault has to answer. */
function serve({ secrets = [CREDENTIAL] } = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return { items: secrets, total: secrets.length };
    return {};
  });
}

function withQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  serve();
});

/**
 * Each scope names a different set of people, so each has its own sentence.
 *
 * A `personal` collection saying what an `org` one says is the defect this
 * component exists to prevent read the other way round: a sentence that is
 * always the same is one nobody reads twice (#982).
 */
describe("SourceAudienceNotice", () => {
  it("names everyone who can view an org collection", async () => {
    withQuery(
      <SourceAudienceNotice
        scope="org"
        collectionName="org_handbook"
        secretId="secret-1"
        needsCredential
      />,
    );

    const sentence = await screen.findByText(/Drive service account/);
    expect(sentence).toHaveTextContent("org_handbook");
    expect(sentence).toHaveTextContent(
      "everyone in this organization who can view that collection",
    );
  });

  it("says only the owner for a personal collection", async () => {
    withQuery(
      <SourceAudienceNotice
        scope="personal"
        collectionName="my_notes"
        secretId="secret-1"
        needsCredential
      />,
    );

    expect(await screen.findByText(/my_notes/)).toHaveTextContent("by you alone");
  });

  it("says the whole deployment for an app collection", async () => {
    withQuery(
      <SourceAudienceNotice
        scope="app"
        collectionName="shared_docs"
        secretId="secret-1"
        needsCredential
      />,
    );

    expect(await screen.findByText(/shared_docs/)).toHaveTextContent("anybody in this deployment");
  });

  it("describes a connector that authenticates with nothing without inventing a credential", async () => {
    // `secret_kind: "none"` is a supported case - a public crawler - and the
    // credential step says so in as many words. A sentence about "the credential
    // this source uses" would contradict the step before it.
    withQuery(
      <SourceAudienceNotice scope="org" collectionName="org_handbook" needsCredential={false} />,
    );

    const sentence = await screen.findByText(/Everything this source ingests/);
    expect(sentence).toHaveTextContent("org_handbook");
    expect(screen.queryByText(/The credential this source uses/)).toBeNull();
  });

  it("names no credential when the vault cannot be read", async () => {
    // A member without `secrets:view` still chooses a collection, and the
    // consequence is the same one - so the sentence drops the name rather than
    // interpolating an empty one.
    serve({ secrets: [] });
    withQuery(
      <SourceAudienceNotice
        scope="org"
        collectionName="org_handbook"
        secretId="secret-1"
        needsCredential
      />,
    );

    expect(await screen.findByText(/The credential this source uses/)).toHaveTextContent(
      "org_handbook",
    );
  });

  it("says an integration under no knowledge base can be searched by nobody yet", async () => {
    withQuery(<SourceAudienceNotice secretId="secret-1" needsCredential />);

    expect(await screen.findByText(/filed under no knowledge base yet/)).toHaveTextContent(
      "decided when it is cloned into one",
    );
  });

  it("says nothing about a collection it was given no scope for", async () => {
    // A name with no scope beside it cannot be described: the picker offers only
    // collections this caller may file under, and one missing from that list is
    // one whose audience this component does not know.
    withQuery(<SourceAudienceNotice collectionName="mystery" needsCredential />);

    expect(await screen.findByText(/filed under no knowledge base yet/)).toBeInTheDocument();
    expect(screen.queryByText(/mystery/)).toBeNull();
  });
});
