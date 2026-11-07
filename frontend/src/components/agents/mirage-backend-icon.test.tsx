import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BRAND_GLYPHS } from "@/lib/brand-glyphs.generated";
import { MirageBackendIcon } from "./mirage-backend-icon";

describe("Mirage integration logos", () => {
  it.each([
    ["airtable", "airtable"],
    ["box", "box"],
    ["chroma", "chroma"],
    ["dify", "dify"],
    ["gcal", "googlecalendar"],
    ["gdrive", "gdrive"],
    ["sharepoint", "sharepoint"],
    ["databricks_volume", "databricks"],
    ["gridfs", "mongodb"],
    ["hf_buckets", "huggingface"],
    ["tidb_filesystem", "tidb"],
  ] as const)("draws the actual %s brand", (backend, brand) => {
    const { container } = render(<MirageBackendIcon backend={backend} />);
    expect(container.querySelector("svg path")?.getAttribute("d")).toBe(
      BRAND_GLYPHS[brand].paths[0]?.d,
    );
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  it.each(["lancedb"])("uses the locally baked %s logo", (backend) => {
    const { container } = render(<MirageBackendIcon backend={backend} />);
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      expect.stringMatching(/^data:image\//),
    );
    expect(container.querySelector("img")).toHaveAttribute("alt", "");
  });

  it.each([
    ["email", "lucide-mail"],
    ["ssh", "lucide-terminal"],
    ["ram", "lucide-memory-stick"],
    ["disk", "lucide-hard-drive"],
    ["future-service", "lucide-plug"],
  ])("gives unbranded %s an appropriate icon", (backend, icon) => {
    const { container } = render(<MirageBackendIcon backend={backend} />);
    expect(container.querySelector("svg")).toHaveClass(icon);
  });
});
