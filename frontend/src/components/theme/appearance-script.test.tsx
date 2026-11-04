import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import { APPEARANCE_BOOTSTRAP_SCRIPT } from "@/lib/appearance";

import { AppearanceScript } from "./appearance-script";

vi.mock("next/headers", () => ({ headers: vi.fn() }));

/** Nonced like the motion script: a blocked script is a glass window that flashes opaque. */
describe("AppearanceScript", () => {
  it("inlines the bootstrap under this request's nonce", async () => {
    vi.mocked(headers).mockResolvedValue(new Headers({ "x-nonce": "abc123" }));
    const element = await AppearanceScript();
    expect(element.props.nonce).toBe("abc123");
    expect(element.props.dangerouslySetInnerHTML).toEqual({ __html: APPEARANCE_BOOTSTRAP_SCRIPT });
  });

  it("carries no nonce attribute where the request had none", async () => {
    vi.mocked(headers).mockResolvedValue(new Headers());
    const element = await AppearanceScript();
    expect(element.props.nonce).toBeUndefined();
  });
});
