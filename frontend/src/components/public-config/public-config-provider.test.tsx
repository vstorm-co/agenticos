import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DEFAULT_PUBLIC_CONFIG, type PublicConfig } from "@/lib/public-config";

import { PublicConfigProvider, usePublicConfig } from "./public-config-provider";

function Readout() {
  const { apiUrl, wsUrl, chatMaxUploadSizeMb, oauthProviders } = usePublicConfig();
  return (
    <ul>
      <li>{apiUrl}</li>
      <li>{wsUrl}</li>
      <li>{chatMaxUploadSizeMb}</li>
      <li>{oauthProviders.join(",")}</li>
    </ul>
  );
}

describe("usePublicConfig", () => {
  it("answers what the provider was seeded with", () => {
    const config: PublicConfig = {
      apiUrl: "https://api.acme.example",
      wsUrl: "wss://api.acme.example",
      siteUrl: "https://console.acme.example",
      chatMaxUploadSizeMb: 25,
      oauthProviders: ["github", "microsoft"],
    };

    render(
      <PublicConfigProvider config={config}>
        <Readout />
      </PublicConfigProvider>,
    );

    expect(screen.getByText("https://api.acme.example")).toBeInTheDocument();
    expect(screen.getByText("wss://api.acme.example")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("github,microsoft")).toBeInTheDocument();
  });

  it("falls back to localhost outside a provider rather than throwing", () => {
    // A leaf mounted alone in a test, or a surface added above the layout's
    // provider, draws against the defaults instead of crashing the page.
    render(<Readout />);

    expect(screen.getByText(DEFAULT_PUBLIC_CONFIG.apiUrl)).toBeInTheDocument();
    expect(screen.getByText(DEFAULT_PUBLIC_CONFIG.wsUrl)).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("google")).toBeInTheDocument();
  });
});
