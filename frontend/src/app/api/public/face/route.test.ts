import { describe, expect, it } from "vitest";

import { GET } from "./route";

const face = (query: string) => GET(new Request(`http://console.test/api/public/face?${query}`));

describe("the widget's drawn face", () => {
  it("is an image that carries its own motion, and the same handle draws the same face", async () => {
    const first = await face("seed=amigo&slot=3");
    const again = await face("seed=amigo&slot=3");
    const svg = await first.text();

    expect(first.headers.get("content-type")).toBe("image/svg+xml; charset=utf-8");
    expect(first.headers.get("x-content-type-options")).toBe("nosniff");
    expect(svg.startsWith("<svg")).toBe(true);
    // The stylesheet travels inside, because none reaches into an image.
    expect(svg).toContain("<style><![CDATA[");
    expect(svg).toContain("prefers-reduced-motion");
    expect(await again.text()).toBe(svg);
  });

  it("thinks when asked, and a slot out of range lets the handle pick the colour", async () => {
    const idle = await (await face("seed=amigo")).text();
    const thinking = await (await face("seed=amigo&thinking=1")).text();
    const odd = await (await face("seed=amigo&slot=99")).text();

    expect(thinking).not.toBe(idle);
    expect(odd).toBe(idle);
  });

  it("parses as XML, which is how a browser reads an image", async () => {
    const svg = await (await face("seed=amigo")).text();

    const parsed = new DOMParser().parseFromString(svg, "image/svg+xml");

    expect(parsed.getElementsByTagName("parsererror")).toHaveLength(0);
  });

  it("draws nothing without a handle", async () => {
    expect((await face("")).status).toBe(404);
  });
});
