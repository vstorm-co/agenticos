import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConnectorIcon } from "./connector-icon";
import { CONNECTOR_LOGOS } from "@/lib/connector-logos.generated";

describe("a connector's mark", () => {
  it.each(["gdrive", "git", "s3", "sharepoint"])("draws %s's own logo, baked in", (type) => {
    const { container } = render(<ConnectorIcon type={type} />);

    expect(container.querySelector("img")).toHaveAttribute("src", CONNECTOR_LOGOS[type]);
  });

  it("knows a stored source by the other spellings of its connector", () => {
    const { container } = render(<ConnectorIcon type="google_drive" />);

    expect(container.querySelector("img")).toHaveAttribute("src", CONNECTOR_LOGOS.gdrive);
  });

  it("draws a website as a globe, and an unknown connector as a database", () => {
    const { container: web } = render(<ConnectorIcon type="web" />);
    const { container: other } = render(<ConnectorIcon type="ftp" />);

    expect(web.querySelector("svg.lucide-globe")).not.toBeNull();
    expect(other.querySelector("svg.lucide-database")).not.toBeNull();
  });
});
