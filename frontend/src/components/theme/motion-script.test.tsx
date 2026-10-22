import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import { MOTION_BOOTSTRAP_SCRIPT } from "@/lib/motion-preference";

import { MotionScript } from "./motion-script";

vi.mock("next/headers", () => ({ headers: vi.fn() }));

/**
 * The inline script carries this request's nonce: the Content-Security-Policy
 * admits no inline script without one, and a blocked script is a flash of motion
 * for everybody who asked for none.
 */
describe("MotionScript", () => {
  it("inlines the bootstrap under this request's nonce", async () => {
    vi.mocked(headers).mockResolvedValue(new Headers({ "x-nonce": "abc123" }));

    const element = await MotionScript();

    expect(element.type).toBe("script");
    expect(element.props.nonce).toBe("abc123");
    expect(element.props.dangerouslySetInnerHTML).toEqual({ __html: MOTION_BOOTSTRAP_SCRIPT });
  });

  it("carries no nonce attribute where the request had none", async () => {
    vi.mocked(headers).mockResolvedValue(new Headers());

    const element = await MotionScript();

    expect(element.props.nonce).toBeUndefined();
  });
});
