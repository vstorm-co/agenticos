import { describe, expect, it } from "vitest";

import { DEFAULT_PUBLIC_CONFIG, readPublicConfig } from "./public-config";

/**
 * The browser's view of a deployment is read from the server's environment on
 * every request, so that one published image serves every deployment (#1544).
 * The parser is pure and the tests hand it plain objects.
 */
describe("readPublicConfig", () => {
  it("answers the localhost defaults when nothing is set", () => {
    expect(readPublicConfig({})).toEqual(DEFAULT_PUBLIC_CONFIG);
  });

  it("reads each URL from its own variable", () => {
    const config = readPublicConfig({
      PUBLIC_API_URL: "https://api.acme.example",
      PUBLIC_WS_URL: "wss://api.acme.example",
      PUBLIC_SITE_URL: "https://console.acme.example",
    });

    expect(config.apiUrl).toBe("https://api.acme.example");
    expect(config.wsUrl).toBe("wss://api.acme.example");
    expect(config.siteUrl).toBe("https://console.acme.example");
  });

  it("strips a trailing slash from every URL, so a joined path is never doubled", () => {
    // `https://site.com//en` in every canonical is what a trailing slash produces.
    const config = readPublicConfig({
      PUBLIC_API_URL: "https://api.acme.example/",
      PUBLIC_WS_URL: "wss://api.acme.example//",
      PUBLIC_SITE_URL: " https://console.acme.example/ ",
    });

    expect(config.apiUrl).toBe("https://api.acme.example");
    expect(config.wsUrl).toBe("wss://api.acme.example");
    expect(config.siteUrl).toBe("https://console.acme.example");
  });

  it("treats a blank URL as unset", () => {
    expect(readPublicConfig({ PUBLIC_API_URL: "  " }).apiUrl).toBe(DEFAULT_PUBLIC_CONFIG.apiUrl);
  });

  it("reads the composer's ceiling as a number", () => {
    expect(readPublicConfig({ CHAT_MAX_UPLOAD_SIZE_MB: "25" }).chatMaxUploadSizeMb).toBe(25);
  });

  it.each(["abc", "0", "-5", "", "NaN"])(
    "falls back to 10 MB when the ceiling is %j, rather than refusing every file",
    (raw) => {
      expect(readPublicConfig({ CHAT_MAX_UPLOAD_SIZE_MB: raw }).chatMaxUploadSizeMb).toBe(10);
    },
  );

  it("keeps the configured providers in the order given", () => {
    expect(readPublicConfig({ OAUTH_PROVIDERS: "microsoft,google" }).oauthProviders).toEqual([
      "microsoft",
      "google",
    ]);
  });

  it("ignores case and whitespace around a provider name", () => {
    expect(readPublicConfig({ OAUTH_PROVIDERS: " Google , GITHUB " }).oauthProviders).toEqual([
      "google",
      "github",
    ]);
  });

  it("drops a provider the sign-in page has no mark for", () => {
    expect(readPublicConfig({ OAUTH_PROVIDERS: "google,okta,,facebook" }).oauthProviders).toEqual([
      "google",
    ]);
  });

  it("reads an empty provider list as no providers, which is how the buttons are turned off", () => {
    expect(readPublicConfig({ OAUTH_PROVIDERS: "" }).oauthProviders).toEqual([]);
  });

  it("offers Google when no provider list is set at all", () => {
    expect(readPublicConfig({}).oauthProviders).toEqual(["google"]);
  });
});
