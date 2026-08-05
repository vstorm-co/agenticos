import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FileIcon, kindOf } from "./file-tile";

/** What a path says about the file at the end of it, as far as an icon cares. */
describe("reading a path", () => {
  it("groups a file by what somebody would do with it", () => {
    expect(kindOf("/chart.png")).toBe("image");
    expect(kindOf("/run.py")).toBe("code");
    expect(kindOf("/report.csv")).toBe("sheet");
    expect(kindOf("/notes.md")).toBe("doc");
    expect(kindOf("/bundle.zip")).toBe("archive");
    expect(kindOf("/Makefile")).toBe("text");
  });

  it("draws an icon for whatever it was given", () => {
    const { container } = render(<FileIcon path="/chart.png" className="h-4" />);

    expect(container.querySelector("svg")).not.toBeNull();
  });
});
