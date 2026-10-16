import { getLocale } from "next-intl/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BUILT_IN_BRANDING } from "@/lib/branding";
import { LOGO_VERSION } from "@/lib/logo.generated";

import RootLayout, { generateMetadata } from "./layout";

vi.mock("next-intl/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next-intl/server")>()),
  getLocale: vi.fn(),
}));

vi.mock("next/font/local", () => ({
  default: () => ({ variable: "", className: "" }),
}));

vi.mock("./globals.css", () => ({}));

// The layout awaits `readBranding`, which reaches BACKEND_URL. Unmocked, this
// spec's result depends on what is listening on :8000 - and a port that accepts
// connections without answering hangs it until the 15s deadline (#1075).
vi.mock("@/lib/branding-server", () => ({
  readBranding: vi.fn(async () => BUILT_IN_BRANDING),
}));

/**
 * `<html lang>` follows the active locale (#619).
 *
 * The root layout is the only layout that renders `<html>`, and it used to
 * hard-code `lang="en"` - so a screen reader on a Polish page announced Polish
 * copy with an English voice, and a crawler read the page as English. An async
 * server component cannot mount under Testing Library, so the layout is called
 * as the function it is and the returned element inspected.
 */
describe("RootLayout", () => {
  beforeEach(() => {
    vi.mocked(getLocale).mockReset();
  });

  it("declares a Polish page as Polish", async () => {
    vi.mocked(getLocale).mockResolvedValue("pl");

    const element = await RootLayout({ children: null });

    expect(element.type).toBe("html");
    expect(element.props.lang).toBe("pl");
  });

  it("declares an English page as English", async () => {
    vi.mocked(getLocale).mockResolvedValue("en");

    const element = await RootLayout({ children: null });

    expect(element.props.lang).toBe("en");
  });
});

/**
 * The built-in favicon's address changes with the mark. A browser keeps a
 * favicon long past its cache header, so a new logo under an unchanged `/icon`
 * went on showing the old one in every tab that had opened the console.
 */
describe("generateMetadata", () => {
  it("versions the built-in favicon and home-screen icon by the mark", async () => {
    const { icons } = await generateMetadata();

    expect(icons).toMatchObject({
      icon: [{ url: `/icon?v=${LOGO_VERSION}` }],
      apple: [{ url: `/apple-icon?v=${LOGO_VERSION}` }],
    });
  });
});
