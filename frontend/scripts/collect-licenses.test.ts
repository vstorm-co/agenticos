import { mkdtempSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { collect, identifiers, noticeFor } from "./collect-licenses";

/**
 * That the image's licence directory holds what the licences oblige.
 *
 * The failure this guards is the quiet one: a package copied into the standalone
 * output without its licence file, and nothing red anywhere. So the cases are the
 * shapes the real tree has - a nested copy, a dev dependency that must not be
 * collected, a package that publishes no licence file at all - and what must be
 * on disk afterwards.
 */

function project(): string {
  const root = mkdtempSync(join(tmpdir(), "collect-licenses-"));
  writeFileSync(join(root, "NOTICE"), "brand marks\n");
  mkdirSync(join(root, "src", "app", "fonts"), { recursive: true });
  writeFileSync(join(root, "src", "app", "fonts", "OFL.txt"), "SIL Open Font License\n");
  mkdirSync(join(root, "licenses", "texts"), { recursive: true });
  writeFileSync(join(root, "licenses", "texts", "MIT.txt"), "MIT License text\n");
  return root;
}

function pkg(
  root: string,
  name: string,
  version: string,
  extra: Record<string, unknown> = {},
  licenseFiles: Record<string, string> = {},
): void {
  const directory = join(root, "node_modules", name);
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, "package.json"), JSON.stringify({ name, version, ...extra }));
  for (const [file, text] of Object.entries(licenseFiles))
    writeFileSync(join(directory, file), text);
}

describe("collect", () => {
  it("copies every licence file of the production closure under the package's path", () => {
    const root = project();
    writeFileSync(
      join(root, "package.json"),
      JSON.stringify({ dependencies: { app: "^1" }, devDependencies: { "only-dev": "^1" } }),
    );
    pkg(
      root,
      "app",
      "1.0.0",
      { license: "MIT", dependencies: { deep: "^2" } },
      { LICENSE: "mit text" },
    );
    pkg(
      root,
      "deep",
      "2.0.0",
      { license: "ISC" },
      { "LICENCE.md": "isc text", COPYING: "copying" },
    );
    pkg(root, "only-dev", "1.0.0", { license: "MIT" }, { LICENSE: "never copied" });
    const out = join(root, "out");

    const collected = collect(root, out);

    expect(collected).toEqual([
      { name: "app", version: "1.0.0", files: ["LICENSE"] },
      { name: "deep", version: "2.0.0", files: ["COPYING", "LICENCE.md"] },
    ]);
    expect(readFileSync(join(out, "node_modules", "app", "LICENSE"), "utf8")).toBe("mit text");
    expect(readdirSync(join(out, "node_modules", "deep")).sort()).toEqual([
      "COPYING",
      "LICENCE.md",
    ]);
    expect(readdirSync(join(out, "node_modules"))).not.toContain("only-dev");
  });

  it("finds a nested copy beside the dependant that needed it", () => {
    const root = project();
    writeFileSync(
      join(root, "package.json"),
      JSON.stringify({ dependencies: { outer: "^1", shared: "^1" } }),
    );
    pkg(
      root,
      "outer",
      "1.0.0",
      { license: "MIT", dependencies: { shared: "^2" } },
      { LICENSE: "outer" },
    );
    pkg(root, "shared", "1.0.0", { license: "MIT" }, { LICENSE: "shared one" });
    pkg(
      join(root, "node_modules", "outer"),
      "shared",
      "2.0.0",
      { license: "MIT" },
      { LICENSE: "shared two" },
    );
    const out = join(root, "out");

    const collected = collect(root, out);

    expect(collected.map((entry) => `${entry.name}@${entry.version}`)).toEqual([
      "outer@1.0.0",
      "shared@1.0.0",
      "shared@2.0.0",
    ]);
    expect(
      readFileSync(join(out, "node_modules", "outer", "node_modules", "shared", "LICENSE"), "utf8"),
    ).toBe("shared two");
  });

  it("writes a NOTICE from the manifest for a package that publishes no licence file", () => {
    const root = project();
    writeFileSync(join(root, "package.json"), JSON.stringify({ dependencies: { bare: "^1" } }));
    pkg(root, "bare", "0.0.1", {
      license: "MIT",
      author: { name: "Somebody", email: "s@example.invalid" },
      repository: { type: "git", url: "https://github.com/x/bare" },
    });
    const out = join(root, "out");

    const collected = collect(root, out);

    expect(collected).toEqual([{ name: "bare", version: "0.0.1", files: [] }]);
    expect(readFileSync(join(out, "node_modules", "bare", "NOTICE"), "utf8")).toBe(
      "bare 0.0.1\nLicence: MIT\n\nThis package publishes no licence file. The copyright holders it names:\n" +
        "  Somebody <s@example.invalid>\n\nSource: https://github.com/x/bare\n",
    );
    expect(readFileSync(join(out, "node_modules", "bare", "LICENSE-MIT.txt"), "utf8")).toBe(
      "MIT License text\n",
    );
  });

  it("fails the build when a licence has no text to place beside such a package", () => {
    const root = project();
    writeFileSync(join(root, "package.json"), JSON.stringify({ dependencies: { lib: "^1" } }));
    pkg(root, "lib", "1.2.4", { license: "LGPL-3.0-or-later", author: "Somebody" });

    expect(() => collect(root, join(root, "out"))).toThrow(
      /lib@1.2.4 ships no licence file and licenses\/texts\/LGPL-3.0-or-later.txt does not exist/,
    );
  });

  it("carries the frontend's own NOTICE and the fonts' OFL", () => {
    const root = project();
    writeFileSync(join(root, "package.json"), JSON.stringify({ dependencies: {} }));
    const out = join(root, "out");

    collect(root, out);

    expect(readFileSync(join(out, "NOTICE"), "utf8")).toBe("brand marks\n");
    expect(readFileSync(join(out, "OFL.txt"), "utf8")).toBe("SIL Open Font License\n");
  });

  it("refuses a production dependency that is not installed, and skips an optional one", () => {
    const root = project();
    writeFileSync(
      join(root, "package.json"),
      JSON.stringify({
        dependencies: { absent: "^1" },
        optionalDependencies: { "other-platform": "^1" },
      }),
    );

    expect(() => collect(root, join(root, "out"))).toThrow(/absent is a production dependency/);

    writeFileSync(
      join(root, "package.json"),
      JSON.stringify({ optionalDependencies: { "other-platform": "^1" } }),
    );
    expect(collect(root, join(root, "out"))).toEqual([]);
  });
});

describe("identifiers", () => {
  it("reads the identifiers out of an expression and nothing else", () => {
    expect(identifiers("MIT")).toEqual(["MIT"]);
    expect(identifiers("(MIT OR Apache-2.0)")).toEqual(["MIT", "Apache-2.0"]);
    expect(identifiers("MIT AND ISC AND MIT")).toEqual(["MIT", "ISC"]);
    expect(identifiers("LGPL-3.0-or-later WITH openssl-exception")).toEqual(["LGPL-3.0-or-later"]);
  });
});

describe("noticeFor", () => {
  it("reads the legacy licenses array and string authors", () => {
    const notice = noticeFor({
      name: "old",
      version: "1.2.3",
      licenses: [{ type: "MIT" }, { type: "Apache-2.0" }],
      author: "Ada <ada@example.invalid>",
      contributors: [{ name: "Grace" }],
    });

    expect(notice).toContain("Licence: MIT OR Apache-2.0");
    expect(notice).toContain("  Ada <ada@example.invalid>\n  Grace\n");
  });

  it("says so when the manifest names nobody", () => {
    expect(noticeFor({ name: "anon", version: "0.0.1", license: "MIT" })).toContain(
      "(none named in package.json)",
    );
  });
});
