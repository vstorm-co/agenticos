import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, it } from "vitest";

it("renders the default itinerary with country outlines, pins and routes without tiles", async () => {
  const catalog = resolve(process.cwd(), "../backend/app/core/catalog");
  const template = await readFile(
    resolve(catalog, "skills/visual-design/templates/itinerary.html"),
    "utf8",
  );
  const host = document.createElement("div");
  host.innerHTML = template;
  document.body.appendChild(host);
  try {
    const scripts = [...document.querySelectorAll("script")];
    expect(scripts.map((script) => script.src).join(" ")).not.toMatch(/leaflet|agenticos-map-2/);
    for (const script of scripts) {
      const source = script.getAttribute("src");
      const content = source
        ? await readFile(resolve(catalog, "artifact_lib", source.replace(/^lib\//, "")), "utf8")
        : (script.textContent ?? "");
      window.eval(content);
    }
    const svg = document.querySelector('#trip svg[role="img"]');
    expect(svg).not.toBeNull();
    if (!svg) throw new Error("The lightweight map did not render");
    expect(svg.querySelectorAll(".aow-country").length).toBeGreaterThan(100);
    expect(svg.querySelectorAll(".aow-pin")).toHaveLength(3);
    expect(svg.querySelectorAll(".aow-route")).toHaveLength(2);
    expect(
      [...svg.querySelectorAll(".aow-pin")].map((pin) => pin.getAttribute("aria-label")),
    ).toEqual(["Warsaw", "Poznań", "Berlin"]);
    expect(document.querySelectorAll("#stops button")).toHaveLength(3);
  } finally {
    host.remove();
  }
});
