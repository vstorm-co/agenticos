import { describe, expect, it } from "vitest";

import {
  READABLE_ATTRS,
  duplicatedInSource,
  isTemplateCopy,
  missingKeys,
  offences,
  unreadKeys,
} from "./check-i18n";

/**
 * That the i18n guard reads what it claims to read.
 *
 * A gate whose failure mode is a green build needs something checking the checker, and
 * this one has had four of those: `check_i18n.py` was patched for a new shape in #199,
 * #246, #249 and #314, each time correctly, and each time the next shape fell between
 * two thresholds. #395 replaced the ten regexes with `ts.createSourceFile`, which is
 * why these are vitest specs rather than `backend/tests/test_check_i18n_*.py` - the
 * guard is TypeScript now, run by bun from `make lint-frontend`.
 *
 * **What is worth asserting here is both halves.** What must be reported is the policy;
 * what must *not* be is equally the policy, because a guard that cries wolf gets
 * switched off. Every near-miss below is a real shape from this tree that a regex read
 * as copy or read past.
 *
 * Each `describe` names the issue whose defect it holds shut. Where a case passed under
 * the Python guard too, it says so: those are forward guards, not evidence for #395.
 */

/**
 * What `isTemplateCopy` reads an interpolation as, since it is handed a body rather
 * than a node. Not a space: whitespace is the discriminator the whole rule turns on,
 * so the placeholder has to be a character no source holds.
 */
const HOLE = "\u0000";

function said(source: string): string[] {
  return offences("sample.tsx", source).map(({ what }) => what);
}

function texts(source: string): string[] {
  return said(source).filter((what) => what.startsWith("text "));
}

describe("a phrase in JSX", () => {
  it("is refused when it sits beside an inline handler (#314)", () => {
    // `mcp-server-list.tsx` rendered `Check connection` and `Settings` verbatim between
    // two items that read `t(…)`, which is what makes them a slip rather than a
    // decision - and the guard read past both because the line holds `=>`.
    const source =
      "<DropdownMenuItem onSelect={() => onEdit(connection)}>Settings</DropdownMenuItem>\n";

    expect(texts(source)).toEqual(["text 'Settings'"]);
  });

  it("is refused when the formatter broke it across lines (#141)", () => {
    // The larger half of #141: prettier puts a sentence on its own line as soon as the
    // element does not fit in 100 characters, and at that point the line the words are
    // on holds neither the `>` of the opening tag nor the `<` of the closing one. Every
    // regex in the Python guard anchored on both.
    const source = [
      '<p className="text-xs">',
      "  No {provider.label} key in the vault yet. Add one here and it is stored for every",
      "  agent in this organization.",
      "</p>",
      "",
    ].join("\n");

    expect(texts(source)).toHaveLength(1);
  });

  it("is refused when a plain node sits alone on its line (#141)", () => {
    // The 404 page's shape, and the one the regexes could not see at all: no
    // interpolation to anchor on and no bracket on the line. `app/not-found.tsx` and
    // `app/global-error.tsx` shipped English to every locale this way.
    const source = [
      '<h1 className="mt-2 text-4xl font-bold">',
      "  Page not found",
      "</h1>",
      "",
    ].join("\n");

    expect(texts(source)).toEqual(["text 'Page not found'"]);
  });

  it("is refused when a count is built the English way (#246)", () => {
    // `{n} runs` is the one shape English builds by suffixing an `s` that no other
    // locale can: Polish declines the noun, so `1 runs` never becomes `1 run`.
    const source = '<span className="x">{entry.run_count} runs</span>\n';

    expect(texts(source)).toEqual(["text '{entry.run_count} runs'"]);
  });

  it("is refused when a single word leads the interpolation (#249)", () => {
    const source = "<DialogTitle>Rotate {secret?.name}</DialogTitle>\n";

    expect(texts(source)).toEqual(["text 'Rotate {secret?.name}'"]);
  });

  it("is refused behind a separator, which is how a row of fragments hid one (#249)", () => {
    // A dot separating one fragment from the next is markup, not a word, so the rule
    // steps over it rather than counting it - otherwise every string inside a row of
    // them would be exempt by virtue of the row.
    const source = "<> · expires {formatDate(inv.expires_at)}</>\n";

    expect(texts(source)).toHaveLength(1);
  });

  it("is refused when two interpolations share it with two words (#314)", () => {
    // `{used} of {max} used` on the members page: the opening `>` belongs to the
    // fragment above and the closing `<` to the guard below, so no line held both.
    const source = [
      "<>",
      '  {inv.used_count ?? 0} of {inv.max_uses ?? "∞"} used',
      "  {inv.email_domain && <> · @{inv.email_domain} only</>}",
      "</>",
      "",
    ].join("\n");

    expect(texts(source).length).toBeGreaterThan(0);
  });

  it("is refused when an element splits the sentence, because that is one message (#425)", () => {
    // `Sign in to <em>{t("workspace")}</em>` is a head, a span and a tail, and five
    // `auth` headings shipped in English as exactly that. The remedy is `t.rich`.
    const source = '<h1>\n  Sign in to <em>{t("yourWorkspace")}</em>\n</h1>\n';

    expect(texts(source)).toEqual(["text 'Sign in to'"]);
  });

  it("is reported on the line the words are on, however deep the indentation", () => {
    // The line is not cosmetic: it is what an `i18n-exempt` is matched against, so a
    // report one line off is an exemption that cannot be written. `global-error.tsx`
    // had one - fourteen spaces of indentation in front of a nine-character phrase,
    // and the report landed on the closing tag below it.
    const source = [
      "<div>",
      "  <div>",
      "    <div>",
      "      <button>",
      "              Try again",
      "      </button>",
      "    </div>",
      "  </div>",
      "</div>",
      "",
    ].join("\n");

    expect(offences("sample.tsx", source)).toEqual([{ line: 5, what: "text 'Try again'" }]);
  });

  it("is refused when it is a single word, as a node sharing its line always was", () => {
    // Not a widening: `<p>Settings</p>` was refused by `JSX_TEXT` all along. What made
    // `only {flag && <Badge />}` pass was the brace on the line, never policy - the
    // Python rule excluded `{` and `}` from the character class by construction.
    expect(texts("<div>only {flag && <Badge />}</div>\n")).toEqual(["text 'only'"]);
  });
});

describe("a phrase that is not copy", () => {
  it("passes when a generic return type sits beside an arrow (#314)", () => {
    // `(() => Promise<void>)` is the shape that made skipping every line holding `=>`
    // look necessary, and skipping them hid the most common thing on a JSX line.
    expect(said("  onTest: (() => Promise<void>) | null;\n")).toEqual([]);
  });

  it("passes when a generic call sits inside an arrow (#314)", () => {
    const source = "  const load = async () => (await apiClient.get<AgentRead[]>(url)).items;\n";

    expect(said(source)).toEqual([]);
  });

  it("passes when a generic spans lines, which is fourteen files in components/ui", () => {
    // The measured cost of a prototype that read text nodes with a regex: about ninety
    // false positives, most of them this. A parser never sees a type argument list as
    // JsxText at all.
    const source = [
      "const Item = React.forwardRef<",
      "  React.ComponentRef<typeof Primitive.Item>,",
      "  React.ComponentPropsWithoutRef<typeof Primitive.Item>",
      ">(({ className, ...props }, ref) => <Primitive.Item ref={ref} {...props} />);",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });

  it("passes when a ternary sits between two JSX branches, which is ten more files", () => {
    // `) : rows.length === 0 ? (` sits between a `/>` and a `<`, one line each way. The
    // other shape the ninety were.
    const source = [
      "{isLoading ? (",
      "  <LoadingState />",
      ") : rows.length === 0 ? (",
      "  <EmptyState title={t('nothingYet')} />",
      ") : (",
      "  <Table rows={rows} />",
      ")}",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });

  it("passes on an ICU plural call, or the rule would forbid its own remedy (#246)", () => {
    const source = '<span>{t("runCount", { count: entry.run_count })}</span>\n';

    expect(said(source)).toEqual([]);
  });

  it("passes on a message call the formatter broke across lines (#314)", () => {
    const source = '<p>\n  {t("savedModelCount", {\n    count: profiles.length,\n  })}\n</p>\n';

    expect(said(source)).toEqual([]);
  });

  it("passes on a named message, which is the remedy for a leading word (#249)", () => {
    const source = '<DialogTitle>{t("rotateNamed", { name: secret.name })}</DialogTitle>\n';

    expect(said(source)).toEqual([]);
  });

  it("passes on a spacer, which is not the interpolation a count needs (#314)", () => {
    // `{" "}` is the space prettier could not leave in the source, not a value. Without
    // that, `{" "} to <span>` reads as the count shape `{n} word`.
    const source = '<>\n  {" "}\n  to <span className="font-medium">{email}</span>\n</>\n';

    expect(said(source).filter((what) => what.includes("' to"))).toEqual([]);
  });

  it("passes on a JSX-only file's imports and props", () => {
    const source = [
      'import { Button } from "@/components/ui";',
      "",
      "export function X({ open }: { open: boolean }) {",
      '  return <Button variant="destructive" type="submit" data-state={open ? "open" : "shut"} />;',
      "}",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });
});

describe("a readable attribute", () => {
  it("refuses a noun passed as an English word (#362)", () => {
    // `<Pager noun="skills">` at six call sites, whose message is `{matched} of {total}
    // {noun}`. It read as translated and rendered `3 of 40 skills` under `pl`.
    const found = said('<Pager page={0} noun="skills" onPage={setPage} />\n');

    expect(found).toEqual(['noun="skills"']);
  });

  it("refuses a term passed as an English word (#362)", () => {
    expect(said('<Fact term="Chunking">{summary}</Fact>\n')).toEqual(['term="Chunking"']);
  });

  it("passes the same props read from the catalog", () => {
    // A forward guard, and it passed under the Python rule too: the remedy the refusals
    // above demand must not itself be refused.
    const source = '<Fact term={t("chunking")}>{t("chunkingSummary", { size })}</Fact>\n';

    expect(said(source)).toEqual([]);
  });

  it("can match every name in the list", () => {
    // Not a drift check - there is one list. What can go wrong is a name the sweep reads
    // as covered and never matches, which fails as a green build.
    for (const name of READABLE_ATTRS) {
      expect(said(`<Thing ${name}="Save changes" />\n`)).toContain(`${name}="Save changes"`);
    }
  });
});

describe("a template literal", () => {
  it("refuses one word beside an interpolation, which is what #395 is", () => {
    // 53 strings in 32 files sat below `TEMPLATE`'s two-word threshold: `aria-label`s
    // like `Remove ${source.name}` and toasts like `${name} updated.`, every one of them
    // rendering in English under `pl`.
    expect(isTemplateCopy(`Remove ${HOLE}`)).toBe(true);
    expect(isTemplateCopy(`${HOLE} updated.`)).toBe(true);
    expect(said("<Button aria-label={`Remove ${source.name}`} />\n")).toEqual([
      "template '`Remove ${source.name}`'",
    ]);
  });

  it("passes an identifier assembled by interpolation, which the threshold was for", () => {
    // `` `audience${key}Hint` `` builds a catalog key and reads as two words only
    // because the interpolation was replaced by one. Whitespace is what separates the
    // two: nobody assembles an identifier with spaces in it.
    expect(isTemplateCopy(`audience${HOLE}Hint`)).toBe(false);
    expect(said("const key = `audience${key}Hint`;\n")).toEqual([]);
  });

  it("refuses a question, which a bare `?` used to exempt", () => {
    // `?` was on the machine-read list for query strings, and it exempted every
    // confirm dialog in the tree: `Archive ${agent.name}?`, `Disconnect "${name}"?`.
    expect(said("<ConfirmDialog title={`Archive ${agent.name}?`} />\n")).toEqual([
      "template '`Archive ${agent.name}?`'",
    ]);
  });

  it("passes a URL and a CSS value", () => {
    expect(isTemplateCopy(`/api/v1/agents/${HOLE}/versions`)).toBe(false);
    expect(isTemplateCopy(`translateY(${HOLE}px)`)).toBe(false);
  });

  it("passes a number and its unit, which is the fourteenth item in #395", () => {
    // A unit is not translated - `KiB` is `KiB` in every locale, and a key holding one
    // hands a translator a symbol they must not touch. One real word beside it makes it
    // a sentence again.
    expect(isTemplateCopy(`${HOLE} KiB`)).toBe(false);
    expect(isTemplateCopy(`${HOLE} min`)).toBe(false);
    expect(isTemplateCopy(`HTTP ${HOLE}`)).toBe(false);
    expect(isTemplateCopy(`${HOLE} files left`)).toBe(true);
  });

  it("passes a class list, which must never become a key (#348)", () => {
    // Answering a false positive by minting a key put 18 Tailwind class lists in the
    // catalog, read back through `cn(t("flexItemsStartGap"))`, where translating one
    // strips the component of its styling.
    const source = 'const cls = cn(`flex items-center gap-2 ${dense ? "py-1" : "py-2"}`);\n';

    expect(said(source)).toEqual([]);
  });
});

describe("a string literal", () => {
  it("refuses a sentence in a ternary", () => {
    expect(said('<Button>{busy ? "Saving changes…" : t("save")}</Button>\n')).toEqual([
      "string 'Saving changes…'",
    ]);
  });

  it("refuses a toast, including one the formatter broke over three lines", () => {
    // The multi-line call is why this is a parser rule: `TOASTS` needed `toast.error(`
    // and the string on one line, so `URL must start with http:// or https://` in
    // `mcp-server-list.tsx` was invisible.
    const source = 'toast.error(\n  "URL must start with http:// or https://",\n);\n';

    expect(said(source)).toEqual(["toast 'URL must start with http:// or https://'"]);
  });

  it("refuses a plural somebody rolled by hand", () => {
    const source = '<span>{n} file{n === 1 ? "" : "s"}</span>\n';

    expect(said(source).filter((what) => what.startsWith("plural "))).toHaveLength(1);
  });

  it("passes a two-token label, an icon name and an import", () => {
    expect(said('import { Button } from "@/components/ui/button";\n')).toEqual([]);
    expect(said('const icon = "chevron-right";\n')).toEqual([]);
    expect(said('const mime = "application/pdf";\n')).toEqual([]);
  });
});

describe("an exemption", () => {
  it("covers the line it is on and the line below", () => {
    const source = "// i18n-exempt: a wire format\nconst out = `result: ${result}`;\n";

    expect(said(source)).toEqual([]);
  });

  it("covers the element it opens, however long the opening tag is", () => {
    // `app/not-found.tsx` is why: three exemptions sat above an `<h1>` whose words are
    // on the third line, because the opening tag carries four Tailwind classes. A
    // two-line window covered the tag and missed the copy.
    const source = [
      "{/* i18n-exempt: rendered outside NextIntlClientProvider */}",
      '<h1 className="text-foreground mt-2 text-4xl font-bold tracking-tight sm:text-5xl">',
      "  Page not found",
      "</h1>",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });

  it("covers a prop several lines inside the element it opens", () => {
    // The half the `<h1>` above does not prove: there the offence *is* the element, so
    // only its own start line is consulted. Here the offence is an attribute four lines
    // in, and nothing but walking up from it to the element reaches the comment.
    const source = [
      "{/* i18n-exempt: the file name is the label, and a path is not translated */}",
      "<Button",
      '  variant="ghost"',
      '  size="icon"',
      "  aria-label={`Remove ${file.path}`}",
      "/>",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });

  it("covers the code below a reason worth two lines", () => {
    // A reason is required, and a required reason is sometimes a sentence. An exemption
    // that only works while it fits on one line fails silently the moment somebody
    // explains themselves properly.
    const source = [
      "// i18n-exempt: the capability's own wire format, which `parseResult` matches",
      "// literally - translating it would break the round-trip it is reassembling",
      "const outputText = `result: ${result}`;",
      "",
    ].join("\n");

    expect(said(source)).toEqual([]);
  });

  it("needs a reason", () => {
    const source = "// i18n-exempt\nconst out = `Remove ${name}`;\n";

    expect(said(source)).toEqual(["template '`Remove ${name}`'"]);
  });

  it("does not blank a comment's own words, because a comment is not read at all", () => {
    // The Python guard had to blank comments before matching, and blanked them by line;
    // a parser never sees one. The sentence in the comment is not copy and the text
    // node beside it is.
    const source = '<p>Nothing yet.</p> // answers "Wrote 1 lines to …"\n';

    expect(texts(source)).toEqual(["text 'Nothing yet.'"]);
  });
});

describe("the catalog, read the other way round", () => {
  const source = (path: string, text: string) => [{ path, text }];

  it("reports a key no component reads (#425)", () => {
    const catalog = { agents: { used: "Used", orphan: "Continue" } };
    const files = source("panel.tsx", 'const t = useTranslations("agents");\n<p>{t("used")}</p>\n');

    expect(unreadKeys(catalog, files)).toEqual(["agents.orphan"]);
  });

  it("reads a key built by interpolation", () => {
    // Seven call sites in this frontend build a key from a module-level table, so a rule
    // that only saw literal calls would report about 150 keys that render fine.
    const catalog = { agents: { scopeRunLabel: "This run", scopeAgentLabel: "This agent" } };
    const files = source(
      "section.tsx",
      'const t = useTranslations("agents");\n{t(`${option.words}Label`)}\n',
    );

    expect(unreadKeys(catalog, files)).toEqual([]);
  });

  it("reads a key a module-level table holds", () => {
    // `SETTINGS_TABS` and `NAV_GROUPS` are both this shape, and the file holding them
    // calls no translator at all.
    const catalog = { nav: { profile: "Profile" } };
    const files = [
      { path: "tabs.ts", text: 'export const TABS = [{ labelKey: "profile" }];\n' },
      { path: "row.tsx", text: 'const t = useTranslations("nav");\n{t(tab.labelKey)}\n' },
    ];

    expect(unreadKeys(catalog, files)).toEqual([]);
  });

  it("reads a kebab-case key a table holds relative to its namespace", () => {
    // 101 keys here are filed under an id like `my-agents`, and a dashboard layout entry
    // is `{ titleKey: "widgets.my-agents.sharedTitle" }` beside a
    // `useTranslations("dashboard")` - so neither the whole key nor its last segment is
    // spelled anywhere.
    const catalog = { dashboard: { widgets: { "my-agents": { sharedTitle: "Shared with you" } } } };
    const files = [
      {
        path: "layouts.ts",
        text: 'export const L = [{ titleKey: "widgets.my-agents.sharedTitle" }];\n',
      },
      { path: "grid.tsx", text: 'const t = useTranslations("dashboard");\n{t(card.titleKey)}\n' },
    ];

    expect(unreadKeys(catalog, files)).toEqual([]);
  });

  it("still reports a kebab-case key nothing holds", () => {
    const catalog = { dashboard: { widgets: { "top-orgs": { gone: "Gone" } } } };
    const files = source("grid.tsx", 'const t = useTranslations("dashboard");\n');

    expect(unreadKeys(catalog, files)).toEqual(["dashboard.widgets.top-orgs.gone"]);
  });

  it("reads a translator bound to another name", () => {
    // `tc`, `ts` and `tAgents` are all in this tree, and `t(` alone would miss them.
    const catalog = { common: { cancel: "Cancel" } };
    const files = source("dialog.tsx", 'const tc = useTranslations("common");\n{tc("cancel")}\n');

    expect(unreadKeys(catalog, files)).toEqual([]);
  });

  it("reads a key read through rich", () => {
    const catalog = { auth: { signInHeading: "Sign in to <em>your workspace.</em>" } };
    const files = source(
      "form.tsx",
      'const t = useTranslations("auth");\n{t.rich("signInHeading", { em })}\n',
    );

    expect(unreadKeys(catalog, files)).toEqual([]);
  });

  it("reports a key a component reads that the catalog does not hold", () => {
    const catalog = { agents: { used: "Used" } };
    const found = missingKeys(
      "panel.tsx",
      'const t = useTranslations("agents");\n<p>{t("renamed")}</p>\n',
      catalog,
    );

    expect(found).toEqual([{ line: 2, what: "renamed (in agents)" }]);
  });

  it("reports a message also written out in a hook, which the sweep never reads", () => {
    // The offence sweep walks `*.tsx` alone, so nineteen toasts in `src/hooks/**` were
    // invisible to it; this rule is anchored on the catalog and reaches a `.ts` file.
    const catalog = { members: { memberRemoved: "Member removed" } };
    const files = source("hook.ts", 'toast.success("Member removed");\n');

    expect(duplicatedInSource(catalog, files).map(({ key }) => key)).toEqual([
      "members.memberRemoved",
    ]);
  });

  it("reports a message written out as a text node (#141, #425)", () => {
    const catalog = { auth: { sign: "Sign in to" } };
    const files = source(
      "heading.tsx",
      '<h1>\n  Sign in to <em>{t("yourWorkspace")}</em>\n</h1>\n',
    );

    expect(duplicatedInSource(catalog, files).map(({ line, key }) => [line, key])).toEqual([
      [2, "auth.sign"],
    ]);
  });

  it("does not report a message that is only part of a longer one", () => {
    // A substring search was the first shape of this rule and it reported
    // `chat.preview.failedToLoad` inside `Failed to load conversations` eleven times.
    const catalog = { chat: { preview: { failedToLoad: "Failed to load" } } };
    const files = source("hook.ts", 'toast.error("Failed to load conversations");\n');

    expect(duplicatedInSource(catalog, files)).toEqual([]);
  });

  it("does not compare a message with an ICU argument", () => {
    const catalog = { members: { inviteSent: "Invitation sent to {email}" } };
    const files = source("hook.ts", "toast.success(t('inviteSent', { email }));\n");

    expect(duplicatedInSource(catalog, files)).toEqual([]);
  });

  it("does not report a literal marked exempt", () => {
    // Two route handlers need it: a handler has no locale to resolve a message in, and
    // the `detail` it falls back to is the words the client ends up showing.
    const catalog = { pages: { settings: { uploadFailed: "Upload failed" } } };
    const files = source(
      "route.ts",
      "// i18n-exempt: a route handler has no locale\nconst e = { detail: 'Upload failed' };\n",
    );

    expect(duplicatedInSource(catalog, files)).toEqual([]);
  });
});
