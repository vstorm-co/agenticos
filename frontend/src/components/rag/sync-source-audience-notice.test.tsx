import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceAudienceNotice } from "./sync-source-audience-notice";

/**
 * Each scope names a different set of people, so each has its own sentence.
 *
 * A `personal` collection saying what an `org` one says is the defect this
 * component exists to prevent read the other way round: a sentence that is
 * always the same is one nobody reads twice (#982).
 */
describe("SourceAudienceNotice", () => {
  it("names everyone who can view an org collection", () => {
    render(
      <SourceAudienceNotice
        scope="org"
        collectionName="org_handbook"
        credentialName="Drive service account"
      />,
    );

    const sentence = screen.getByText(/Drive service account/);
    expect(sentence).toHaveTextContent("org_handbook");
    expect(sentence).toHaveTextContent(
      "everyone in this organization who can view that collection",
    );
  });

  it("says only the owner for a personal collection", () => {
    render(
      <SourceAudienceNotice scope="personal" collectionName="my_notes" credentialName="My token" />,
    );

    expect(screen.getByText(/my_notes/)).toHaveTextContent("by you alone");
  });

  it("says the whole deployment for an app collection", () => {
    render(
      <SourceAudienceNotice scope="app" collectionName="shared_docs" credentialName="Ops key" />,
    );

    expect(screen.getByText(/shared_docs/)).toHaveTextContent("anybody in this deployment");
  });

  it("says an integration under no knowledge base can be searched by nobody yet", () => {
    render(<SourceAudienceNotice credentialName="Drive service account" />);

    expect(screen.getByText(/filed under no knowledge base yet/)).toHaveTextContent(
      "decided when it is cloned into one",
    );
  });

  it("names no credential when the vault cannot be read", () => {
    // A member without `secrets:view` still chooses a collection, and the
    // consequence is the same one - so the sentence drops the name rather than
    // interpolating an empty one.
    render(<SourceAudienceNotice scope="org" collectionName="org_handbook" />);

    expect(screen.getByText(/The credential this source uses/)).toHaveTextContent("org_handbook");
  });

  it("says nothing about a collection it was given no scope for", () => {
    // A name with no scope beside it cannot be described: the picker offers only
    // collections this caller may file under, and one missing from that list is
    // one whose audience this component does not know.
    render(<SourceAudienceNotice collectionName="mystery" />);

    expect(screen.getByText(/filed under no knowledge base yet/)).toBeInTheDocument();
    expect(screen.queryByText(/mystery/)).not.toBeInTheDocument();
  });
});
