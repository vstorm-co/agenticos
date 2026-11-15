import { expect, it } from "vitest";
import { isNewerRelease, memberReleaseNotes, parseVersion } from "./releases";

it.each([
  ["1.28.0", "1.29.0", true],
  ["1.9.0", "1.10.0", true],
  ["1.0.9", "1.0.10", true],
  ["1.28.0", "v1.28.0", false],
  ["1.29.0", "1.28.9", false],
  ["1.29.0-rc.1", "1.29.0", true],
  ["1.30.0-dev", "1.29.0", false],
  ["1.29.0+build.2", "1.29.0+build.3", false],
  ["1.29.0", "1.30.0-beta.1", false],
  ["development", "1.29.0", false],
  ["1.29.0", "latest", false],
])("compares %s to stable release %s", (current, latest, expected) => {
  expect(isNewerRelease(current, latest)).toBe(expected);
});
it.each([
  "1.2",
  "1.2.3.4",
  "01.2.3",
  "1.2.3-01",
  "1.2.3-beta..1",
  "1.2.3+build..1",
  "99999999999999999.1.1",
])("refuses invalid version %s", (value) => {
  expect(parseVersion(value)).toBeNull();
});

it("leaves a release's operator sections out of the notes a member reads", () => {
  const body = [
    "### Fixed",
    "",
    "- Charts render again.",
    "",
    "### Upgrading",
    "",
    "- Run migration 0320 before restarting the worker.",
    "",
    "### Notes for operators",
    "",
    "- The early evaluation migrations retain `capability_requested`.",
    "",
    "### Added",
    "",
    "- Folders in Documents.",
  ].join("\n");
  const member = memberReleaseNotes(body);
  expect(member).toContain("Charts render again.");
  expect(member).toContain("Folders in Documents.");
  expect(member).not.toMatch(/Upgrading|migration 0320|Notes for operators|capability_requested/);
});

it("ends an operator section at the next heading of its level or above, whichever level it uses", () => {
  const body =
    "## Upgrading\n\nRestart the worker.\n\n### Detail\n\nStill operators.\n\n## Added\n\nNew page.";
  expect(memberReleaseNotes(body).trim()).toBe("## Added\n\nNew page.");
});

it("leaves notes with nothing for operators as they are, and empties notes that held only that", () => {
  expect(memberReleaseNotes("### Fixed\n\n- A fix.")).toBe("### Fixed\n\n- A fix.");
  expect(memberReleaseNotes("### Upgrading\n\n- Migrate first.").trim()).toBe("");
});

it("reads a shell comment in an operator's code block as code, not as the section's end", () => {
  const body = [
    "### Upgrading",
    "",
    "```bash",
    "# back up first",
    "pg_dump agenticos > backup.sql",
    "```",
    "",
    "### Fixed",
    "",
    "- A fix.",
  ].join("\n");
  expect(memberReleaseNotes(body)).toBe("### Fixed\n\n- A fix.");
});

it("keeps a block open past the other fence character and a shorter run of its own", () => {
  const body = [
    "### Fixed",
    "",
    "````markdown",
    "```",
    "~~~",
    "### Upgrading",
    "````",
    "",
    "- A fix.",
  ].join("\n");
  expect(memberReleaseNotes(body)).toBe(body);
});

it("cuts an operator section at the top level too", () => {
  expect(memberReleaseNotes("# Upgrading\n\nMigrate first.\n\n# Added\n\nNew page.")).toBe(
    "# Added\n\nNew page.",
  );
});

it.each(["### Upgrading ###", "   ## Notes for operators", "  ### Upgrading ###  "])(
  "recognizes the Markdown operator heading %s",
  (heading) => {
    expect(memberReleaseNotes(`${heading}\n\nMigrate first.\n\n   # Added #\n\nNew page.`)).toBe(
      "# Added #\n\nNew page.",
    );
  },
);
