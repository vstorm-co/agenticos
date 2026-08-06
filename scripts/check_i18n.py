#!/usr/bin/env python3
"""Refuse copy that a component wrote itself.

Every user-facing string in the frontend comes from `messages/en.json` through
`next-intl`, and the rule survives exactly as long as something checks it: a
convention that is only written down gets broken by the next feature, silently,
and the Polish UI ships half in English. That is what happened here - nine
hundred strings across a hundred and forty files, in a repository whose own
`.claude/rules/frontend.md` says never to hardcode copy.

What it looks for, in `frontend/src/**/*.tsx`:

* a JSX text node holding words - `<p>Nothing yet.</p>`;
* a word-bearing string in an attribute a person reads: `placeholder`,
  `aria-label`, `title`, `alt`, and the label-ish props components take;
* `toast.success("…")` and friends, which are as user-facing as anything on
  screen and read like plumbing;
* a sentence built by concatenation - `` `Access to ${name}` `` - which is where
  copy hides best, being neither a text node nor an attribute nor a plain string;
* a text node holding an interpolation as well as words - `Owned by {email}`,
  `{n} runs`, `Rotate {name}` - and the plural somebody rolled by hand beside it,
  `{n} file{n === 1 ? "" : "s"}`, which is a sentence only English can build that way.
  These four rules read the file as one string rather than a line at a time, because
  the formatter breaks a text node across lines whenever it is long enough and every
  rule here anchors on a `>` and a `<` (#314).

What it deliberately does not look at:

* tests, which assert the copy and must name it;
* `src/app/[locale]/(dashboard)/dev/**`, a playground for looking at components
  that is not part of the product;
* anything a person never reads - `className`, `href`, `data-*`, `id`, `type`;
* a *plain* text node broken across lines - `<p>` newline `Nothing yet.` newline
  `</p>`. `JSX_TEXT` still reads one line at a time. Joining it the way the
  interpolation rules now are reports 70 more nodes across 42 files, 54 of them real
  copy and the rest the `) : cond ? (` a ternary leaves between two elements, which
  wants a discriminator of its own. That is #141, a copy migration of its own size
  rather than part of closing #314.

False positives get an inline `{/* i18n-exempt: why */}` or a trailing
`// i18n-exempt: why`. The comment is required to carry a reason, because "this
one is fine" is the sentence that turns a gate into a rubber stamp.

Two more rules read the catalog and ask a question of the source, rather than reading
the source and asking a question of it - which is why neither needs the parser #395
wants, and why both find copy in a `.ts` file that the sweep above has never opened:

* `unread_keys` - a key nothing reads. 141 of them, and 82 had a Polish translation
  somebody had written for nobody. The extraction pass sometimes lifted a string into
  the catalog and left the component reading the literal, so both halves looked clean
  while the English stayed on screen (#425);
* `duplicated_in_source` - a message whose words are also written out somewhere. That
  is the other half of the same defect, and it is what points at the line.

**A false positive takes an exemption. It never takes a key.** Answering one by
moving the offending text into `messages/en.json` silences the guard and hands a
translator something nobody reads: the migration that first ran this script did
exactly that 166 times, filing 18 Tailwind class lists and 148 fragments of
JavaScript source under keys with names like `caseStatsReturn` (#348).
`frontend/messages/catalog.test.ts` now refuses both shapes, because neither the
offence sweep nor `missing_keys` can see them - a class list reaching `cn()`
through `t()` carries no `className`, and a key that exists is a key that exists.
"""

from __future__ import annotations

import json
import re
import sys
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
CATALOG = ROOT / "frontend" / "messages" / "en.json"

SKIPPED_DIRS = ("/dev/",)
SKIPPED_NAMES = (".test.tsx", ".test.ts", ".spec.ts", ".stories.tsx", ".generated.ts")

# Props a component renders for a person to read. A fixed list, which is the
# whole weakness of the rule: copy passed through a name that is not here is
# copy this script cannot see, and it stays invisible until somebody notices it
# in English under `pl`. `noun` and `term` were added after exactly that (#362) -
# `<Pager noun="skills">` at six call sites and `<Fact term="Chunking">` at four,
# all of them rendered verbatim in every locale. Add the name when a component
# starts taking copy through a new one; the alternative is #395's parser, which
# would read the prop's *value* rather than trusting its name.
READABLE_ATTRS = (
    "placeholder",
    "aria-label",
    "alt",
    "title",
    "label",
    "description",
    "emptyMessage",
    "confirmLabel",
    "cancelLabel",
    "submitLabel",
    "heading",
    "subtitle",
    "noun",
    "term",
)
ATTR = re.compile(rf'\b({"|".join(READABLE_ATTRS)})="([^"]*)"')
JSX_TEXT = re.compile(r"(?<!=)>\s*([^<>{}\n][^<>{}\n]*?)\s*<")
TOASTS = re.compile(r'\btoast\.(?:success|error|info|warning|message)\(\s*"([^"]+)"')
# Copy hiding in an expression rather than in a text node - `{busy ? "Saving…" :
# "Save"}`, a ternary in a prop, a sentence pushed into an array. Two words is the
# threshold: it is what separates a sentence from an identifier, and every one-word
# label is already caught as a text node or an attribute.
SENTENCE = re.compile(r'"([A-Z][^"\n]*?\s[^"\n]*?)"')
NOT_A_SENTENCE = re.compile(
    r"^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s?[-/]\s?|"  # "Foo / Bar" style tokens
    r"[A-Z]{2,}\s|.*\b(?:px|rem|vh|vw|deg)\b)"
)
# Copy in a text node that also holds an interpolation - `Owned by {email}`,
# `Showing {n} of {m} rows`. `JSX_TEXT` excludes braces by construction, so the first
# sweep read straight past this whole class and left it in English. The interpolation
# may nest - `t("x", { count: n })` is one - so the body is bounded by the angle
# brackets alone and taken apart by `interpolations` rather than by a second regex.
MIXED = re.compile(r"(?<!=)>([^<>]*\{[^<>]*\}[^<>]*)<")
# A count built the English way: an interpolation and then the noun it counts, `{n}
# runs`, `{count} documents`. English is the only language where a trailing `s` makes
# the plural - Polish declines the noun, so `1 runs` never becomes `1 run` and the word
# cannot agree with the number at all. The fix is the count inside an ICU `plural`
# message, which a hand-built text node can never become. `MIXED` reads straight past
# this: one trailing word is below its two-word threshold. Leading punctuation is
# stepped over the way `LEAD` steps over it, so `· @{domain} only` is read as the count
# shape it is rather than exempted by the separator in front of it.
COUNT = re.compile(r"(?<!=)>[^A-Za-z<>{}]*\{([^{}]+)\}\s+([A-Za-z]{2,})\s*<")
# The mirror image, and the one both of those miss: a single word *before* the
# interpolation. `Rotate {secret.name}`, `chunk {chunk.chunk}`, `Invited {date}` are
# one message with a named parameter each, and each rendered its English word verbatim
# under `pl` while the guard read past it - `MIXED` wants two words and `COUNT` only
# reads the word that follows. Leading punctuation is stepped over rather than counted:
# a separator dot in front of the word is how the same string reads inside a row of them.
LEAD = re.compile(r"(?<!=)>[^A-Za-z<>{}]*([A-Za-z]{2,})\s+\{([^{}]+)\}")
# What tells a count from a conditional that renders an element - the element. These
# rules used to refuse an angle bracket anywhere in the interpolation, which kept
# `{cond && <span/>} more` out but also every count computed with a lambda: the `>` of
# `=>` broke the match, so `{docs.reduce((sum, d) => sum + d.chunk_count, 0)} vectors`
# passed the guard and had to be found by hand (#246).
JSX_ELEMENT = re.compile(r"</|/>|<[A-Za-z]")
# A plural somebody rolled by hand: `{n} chunk{n === 1 ? "" : "s"}`. English is the
# only language where this works, which is the point of `plural` in an ICU message.
PLURAL = re.compile(r'\?\s*"([A-Za-z]*)"\s*:\s*"([A-Za-z]*)"')
# The other half of the same habit, where the singular is spelled out: `count === 1 ?
# "1 skill" : ...`. Caught by its digit, which `SENTENCE` requires a capital instead of.
NUMBERED = re.compile(r'"(\d+\s+[A-Za-z][^"\n]*)"')
# A sentence built by concatenation - `Access to ${name}`, `${n} of ${total} shown`.
# A template literal is where copy hides best: it is not a text node, not an attribute
# and not a plain string, so every other rule here reads past it.
TEMPLATE = re.compile(r"`([^`\n]*\$\{[^{}`]*\}[^`\n]*)`")
# Two words with real whitespace between them. `audience${key}Hint` builds a catalog
# key and reads as two words only because the interpolation was replaced by one.
TWO_WORDS = re.compile(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}")
# A URL, a query string, a CSS value, a header - built by interpolation and read by
# a machine.
MACHINE_READ = re.compile(r"[/?&=<>#]|\b(?:px|rem|deg|vh|vw|attachment)\b")
EXEMPT = re.compile(r"i18n-exempt:\s*\S")
WORDS = re.compile(r"[A-Za-z]{2,}")
# What sits in front of the `<` of a TypeScript type argument list, which is the other
# `>` that looks like the end of a JSX tag. A generic is always welded to the identifier
# it parameterises - `useState<`, `Promise<`, `React.forwardRef<` - where a JSX tag opens
# after whitespace, `(`, `{` or `>`, and never after a name. (`</` is a closing tag and
# not a generic, which is what keeps `{n} vectors</span>` readable.)
GENERIC = re.compile(r"[A-Za-z0-9_$\]]")
# An HTML entity is punctuation somebody spelled out. Removed before a body is judged
# to be prose, so `&ldquo;` does not read as a semicolon.
ENTITY = re.compile(r"&(?:[a-zA-Z]+|#\d+);")
# Reading the file as one string means a `>` and a `<` on different lines can be the
# two ends of something that is not a text node at all - a `return (` between two JSX
# blocks, an object of icons, a switch arm. Copy is words and punctuation; these are
# the characters that say the body is code.
NOT_PROSE = re.compile(r"[;=\[\]`|\\^~]")
# An interpolation that carries neither a letter nor a digit is markup: `{" "}` is the
# space the formatter could not leave in the source, not a value somebody reads.
VALUE = re.compile(r"[A-Za-z0-9]")
# A word-bearing string that is still not copy: an icon name, a CSS-ish token, a
# path, a MIME type, a locale tag. Matched whole, so "Save changes" never hits it.
NOT_COPY = re.compile(
    r"^(?:[a-z0-9-]+(?:/[a-z0-9.*+-]+)+|[a-z]+(?:-[a-z0-9]+)+|[A-Za-z]+\.[A-Za-z]{2,4}|"
    r"https?://\S+|&[a-z]+;|[A-Z_]{2,}|\d+(?:\.\d+)?\s*\w{0,3})$"
)


def is_copy(value: str) -> bool:
    """Whether a string is something a person reads, rather than a token."""
    stripped = value.strip()
    if len(stripped) < 2 or not WORDS.search(stripped):
        return False
    return not NOT_COPY.match(stripped)


def is_plural_pair(first: str, second: str) -> bool:
    """Whether two ternary branches are one word and its plural.

    Narrow on purpose: `dir === "asc" ? "desc" : "asc"` is two tokens, not copy, and
    only the `s` shapes - `"" : "s"`, `"file" : "files"` - are a plural in disguise.
    """
    if {first, second} == {"", "s"}:
        return True
    return bool(first) and bool(second) and (second == f"{first}s" or first == f"{second}s")


def readable(lines: list[str]) -> list[str]:
    """The lines with everything a rule must not read blanked out, lengths kept.

    Comments explain the copy and often quote it - "answers \\"Wrote 1 lines to …\\""
    is a sentence about a string, not one - and an `i18n-exempt: why` takes its line
    and the one below it out, which is where the comment lands after formatting.

    Blanked rather than dropped so that every offset still points at the character it
    points at in the file. `node_offences` joins these back into one string and maps a
    match to the line it started on, which only works while the lengths agree.
    """
    blanked: list[str] = []
    in_comment = False
    for number, line in enumerate(lines, 1):
        was_in_comment = in_comment
        if "/*" in line and "*/" not in line[line.index("/*") :]:
            in_comment = True
        elif "*/" in line:
            in_comment = False
        exempt = EXEMPT.search(line) or (number >= 2 and EXEMPT.search(lines[number - 2]))
        if was_in_comment or line.strip().startswith(("//", "*", "/*")) or exempt:
            blanked.append(" " * len(line))
            continue
        # Only the code half of a line that also carries a comment: `<p>Done</p> // why`
        # is copy, and the sentence in the comment is not.
        for opener in ("//", "/*"):
            if opener in line:
                cut = line.index(opener)
                line = line[:cut] + " " * (len(line) - cut)
        blanked.append(line)
    return blanked


def mask_generics(text: str) -> str:
    """Blank every `Identifier<…>`, length kept.

    A type argument list is the only other thing in a `.tsx` file that closes with a
    `>`, and it is what made `onTest: (() => Promise<void>) | null` read as the text
    node `Promise`. That one shape is why the whole sweep used to skip any line
    holding `=>` - an inline handler, the most common thing on a JSX line - and hid
    `<DropdownMenuItem onSelect={() => onEdit(c)}>Settings</DropdownMenuItem>` (#314).

    Removing the type instead of the line is what makes ungating it safe: it took the
    eleven false positives ungating alone reported down to none.
    """
    chars = list(text)
    index = 1
    while index < len(chars) - 1:
        opens_a_type = (
            chars[index] == "<" and GENERIC.match(chars[index - 1]) and chars[index + 1] != "/"
        )
        if not opens_a_type:
            index += 1
            continue
        depth, scan = 0, index
        while scan < len(chars):
            # `useState<() => void>` closes at its own `>`, not at the lambda's.
            if chars[scan] == "<":
                depth += 1
            elif chars[scan] == ">" and chars[scan - 1] != "=":
                depth -= 1
                if depth == 0:
                    break
            scan += 1
        if scan == len(chars):
            index += 1
            continue
        for blank in range(index, scan + 1):
            if chars[blank] != "\n":
                chars[blank] = " "
        index = scan + 1
    return "".join(chars)


def interpolations(body: str) -> tuple[str, list[str]]:
    """A text node's words, and the expressions interpolated into them.

    Brace-counting rather than `\\{[^{}]*\\}` because an interpolation nests -
    `t("rotateNamed", { name })` is one - and because a node that ends inside one,
    `{a} of {b} used {cond &&` cut short by the element that follows it, is still a
    node whose words are `of` and `used`.
    """
    words: list[str] = []
    found: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "{":
            depth += 1
            if depth == 1:
                current = []
                continue
        elif char == "}" and depth:
            depth -= 1
            if not depth:
                found.append("".join(current))
                words.append(" ")
                continue
        if depth:
            current.append(char)
        else:
            words.append(char)
    if depth:
        found.append("".join(current))
    return "".join(words), found


def is_prose(body: str) -> bool:
    """Whether what is left between the interpolations reads as copy rather than code."""
    return not NOT_PROSE.search(ENTITY.sub(" ", body))


def holds_a_value(expression: str) -> bool:
    """Whether an interpolation renders something, rather than being markup or a guard."""
    return bool(VALUE.search(expression)) and not JSX_ELEMENT.search(expression)


def node_offences(probe: str) -> list[tuple[int, str]]:
    """The rules that read a text node whole, over the file joined back together.

    A text node is whatever sits between a `>` and the next `<`, and the formatter
    breaks one across lines the moment it is long enough - which is why
    `{inv.used_count} of {inv.max_uses} used` passed a guard reading one line at a
    time: neither bracket is on its line. Joining is only safe once the `>` of a type
    argument list is gone, hence `mask_generics`.
    """
    starts: list[int] = []
    offset = 0
    for line in probe.split("\n"):
        starts.append(offset)
        offset += len(line) + 1

    def at(match: re.Match[str]) -> int:
        return bisect_right(starts, match.start())

    def said(match: re.Match[str], group: int = 0) -> str:
        return " ".join(match.group(group).split())

    found: list[tuple[int, str]] = []
    for match in MIXED.finditer(probe):
        words, expressions = interpolations(match.group(1))
        if not any(holds_a_value(one) for one in expressions):
            continue
        if len(WORDS.findall(words)) >= 2 and is_prose(words):
            found.append((at(match), f"text {said(match, 1)!r}"))
    for match in COUNT.finditer(probe):
        if is_copy(match.group(2)) and holds_a_value(match.group(1)):
            found.append((at(match), f"count {said(match)!r}"))
    for match in LEAD.finditer(probe):
        # `&&` and `||` in the interpolation make it a guard rather than a value,
        # and the word in front of one belongs to whatever renders around it.
        guard = re.search(r"&&|\|\|", match.group(2))
        if is_copy(match.group(1)) and holds_a_value(match.group(2)) and not guard:
            found.append((at(match), f"text {said(match)!r}"))
    return found


def offences(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    source = readable(path.read_text().splitlines())
    probe = mask_generics("\n".join(source))
    masked = probe.split("\n")
    for number, line in enumerate(source, 1):
        stripped = line.strip()
        for match in ATTR.finditer(line):
            if is_copy(match.group(2)):
                found.append((number, f'{match.group(1)}="{match.group(2)}"'))
        for match in JSX_TEXT.finditer(masked[number - 1]):
            # `percent >= 80 && "text-amber-600"` reads as a text node to a regex.
            # An operator between the angle brackets means it is an expression.
            if is_copy(match.group(1)) and not re.search(r"&&|\|\||=>", match.group(1)):
                found.append((number, f"text {match.group(1)!r}"))
        for match in () if "className" in line else TEMPLATE.finditer(line):
            body = re.sub(r"\$\{[^{}]*\}", "\x00", match.group(1))
            if TWO_WORDS.search(body) and not MACHINE_READ.search(body):
                found.append((number, f"template {match.group(1)!r}"))
        for match in PLURAL.finditer(line):
            if is_plural_pair(match.group(1), match.group(2)):
                found.append((number, f"plural {match.group(0)!r}"))
        for match in NUMBERED.finditer(line):
            if is_copy(match.group(1)):
                found.append((number, f"string {match.group(1)!r}"))
        for match in TOASTS.finditer(line):
            if is_copy(match.group(1)):
                found.append((number, f"toast {match.group(1)!r}"))
        # Only where a string literal can reach the screen: an import path or a
        # `cn(...)` argument holds spaces too, and neither is copy.
        if not stripped.startswith(("import ", "export ", "from ")) and "className" not in line:
            for match in SENTENCE.finditer(line):
                value = match.group(1)
                if is_copy(value) and not NOT_A_SENTENCE.match(value):
                    found.append((number, f"string {value!r}"))
    found += node_offences(probe)
    return sorted(found)


def missing_keys(path: Path, catalog: dict) -> list[tuple[int, str]]:
    """Keys a file reads that the catalog does not hold.

    The other half of the rule. The guard above catches copy that never made it *out*
    of a component; this catches a key that never made it *in* - a rename, a typo, or a
    file whose translator is scoped to one namespace while its keys were filed under
    another, which renders the key itself on screen and reports an error nobody sees
    until a person opens that page.
    """
    text = path.read_text()
    namespaces = re.findall(r'useTranslations\(\s*"([^"]+)"', text) + re.findall(
        r'getTranslations\(\s*"([^"]+)"', text
    )
    if not namespaces:
        return []
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(("//", "*", "/*")):
            continue
        for key in re.findall(r'\bt\(\s*"([^"]+)"', line):
            if not any(_holds(catalog, f"{namespace}.{key}") for namespace in namespaces):
                found.append((number, f"{key} (in {', '.join(namespaces)})"))
    return found


# What binds a translator to a namespace: `const t = useTranslations("agents")`, and the
# awaited `getTranslations` a server component uses. The *name* is captured because it is
# not always `t` - `tc`, `ts` and `tAgents` are all in this tree - and a rule that read
# only `t(` would call every key those three name dead.
TRANSLATOR = re.compile(
    r"\b([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?(?:use|get)Translations\(\s*(?:\"([^\"]*)\")?\s*\)"
)
# A string that could be the name of a key. A module-level table of labels cannot call a
# translator, so it holds keys - `{ labelKey: "agentsTitle" }` - and the component reads
# them back through `t(item.labelKey)`, which names nothing this script can resolve.
KEY_SHAPED = re.compile(r'"([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)*)"')
# A message with an ICU argument in it cannot be compared against a run of source: the run
# would have to hold the braces too, and a component writing `{count, plural, …}` by hand
# is a different defect with its own rule.
ARGUMENT = re.compile(r"[{}<>]")
# A run of prose in a `.tsx` file: whatever sits between the characters that end one. A
# quote ends a string, a brace ends a text node at an interpolation, an angle bracket ends
# it at the next element - so `Sign in to <em>{t("workspace")}</em>` is the run `Sign in to`
# and the run `workspace`, either of which can be compared against a whole message.
RUN = re.compile(r"""[^<>{}"'`\n]+""")


def key_reads(text: str) -> tuple[set[str], list[re.Pattern[str]]]:
    """Every catalog key one file names outright, and the patterns it builds by hand.

    Two shapes, because a component uses both. `t("pickProviderFirst")` names one key and
    resolves against the file's namespaces. `` t(`${option.words}Label`) `` names a family
    of them, and the interpolation is whatever a module-level table holds - so it becomes
    `^\\w*Label$` rather than a key, and any key it could build counts as read.

    Namespaces are unioned across the file rather than tracked per binding: one file holds
    up to seven components with a `t` each, and telling which `t` is in scope on a line is
    the parse this script does not do. Over-reading is the safe direction here - it reports
    fewer dead keys, never a live one.
    """
    bindings = TRANSLATOR.findall(text)
    if not bindings:
        return set(), []
    namespaces = {namespace for _, namespace in bindings}
    names = sorted({name for name, _ in bindings})
    call = re.compile(rf'\b(?:{"|".join(names)})(?:\.rich|\.markup|\.has)?\(\s*(["`])(.*?)\1', re.S)
    named: set[str] = set()
    built: list[re.Pattern[str]] = []
    for quote, body in call.findall(text):
        for namespace in namespaces:
            prefix = re.escape(f"{namespace}.") if namespace else ""
            if quote == '"':
                named.add(f"{namespace}.{body}" if namespace else body)
            else:
                parts = [re.escape(part) for part in re.split(r"\$\{[^{}]*\}", body)]
                built.append(re.compile("^" + prefix + r"\w*".join(parts) + "$"))
    return named, built


def unread_keys(catalog: dict, sources: list[Path]) -> list[str]:
    """Catalog keys nothing in the frontend reads.

    `missing_keys` run the other way round, and it catches what neither that sweep nor the
    offence sweep can: the extraction pass that produced this catalog sometimes lifted a
    string into a key and left the component reading the literal beside it. Both halves
    then look clean - the key is valid, and the line the guard cannot parse is a line it
    reports nothing about - while the English stays on screen under every locale. `Continue`
    on the sync wizard and `(inactive)` in the bot picker shipped that way (#425).

    A key counts as read when a translator names it, when a `` t(`…`) `` pattern could
    build it, or when its own name appears as a plain string anywhere in the frontend -
    the last because a table of keys is read back through `t(item.labelKey)`, and this
    script cannot follow the table to the call. That third clause is loose on purpose: it
    is what makes the rule safe to fail a build on, and it is also the ceiling on what the
    rule can find. `rag.error`, `rag.pending` and `rag.running` were dead and it read them
    as live, because `"error"` is a plain string in half the files here; they had to be
    deleted by hand. Following the table to the call would need #395's parser.
    """
    named: set[str] = set()
    built: list[re.Pattern[str]] = []
    spelled: set[str] = set()
    for path in sources:
        text = path.read_text()
        file_named, file_built = key_reads(text)
        named |= file_named
        built += file_built
        spelled |= set(KEY_SHAPED.findall(text))
    return sorted(
        key
        for key in catalog_keys(catalog)
        if key not in named
        and key not in spelled
        and key.rsplit(".", 1)[-1] not in spelled
        and not any(pattern.match(key) for pattern in built)
    )


def duplicated_in_source(catalog: dict, sources: list[Path]) -> list[tuple[Path, int, str, str]]:
    """Catalog messages whose words are also sitting in the frontend, written out.

    The signature of #425, and the half `unread_keys` cannot see on its own: a key read
    *somewhere* while another component spells the same sentence out. It is also the only
    rule here that reaches a `.ts` file - `offences` walks `*.tsx` alone, so every
    `toast.success("Member removed")` in `src/hooks/**` had been invisible to it since the
    guard was written.

    Anchored on the catalog rather than on the source, which is what keeps it cheap and
    what makes it worth having beside a guard that cannot read a text node broken over two
    lines (#141). There is no JSX to parse: the sentence is already known, so the file is
    cut on the characters that end a run of prose - the quotes, the braces and the angle
    brackets - and each run is compared whole. That finds the words wherever they sit: in
    a string, in an attribute, or in a text node with an `<em>` after it. All five `auth`
    headings were the last of those, and none of them is inside quotes.

    Whole runs rather than a substring search, which was the first shape and reported
    `Failed to load` inside `Failed to load conversations` eleven times. Skipped: a message
    holding an ICU argument or a tag, which no run can equal verbatim; and anything under
    two words, where a match says nothing.
    """
    wanted = {
        value: key
        for key, value in catalog_entries(catalog)
        if is_copy(value) and not ARGUMENT.search(value) and len(value.split()) >= 2
    }
    found: list[tuple[Path, int, str, str]] = []
    for path in sources:
        lines = readable(path.read_text().splitlines())
        starts: list[int] = []
        offset = 0
        for line in lines:
            starts.append(offset)
            offset += len(line) + 1
        for run in RUN.finditer("\n".join(lines)):
            words = run.group(0).strip()
            key = wanted.get(words)
            if key is not None:
                found.append((path, bisect_right(starts, run.start()), key, words))
    return sorted(found)


def catalog_entries(node: object, prefix: str = "") -> list[tuple[str, str]]:
    if isinstance(node, str):
        return [(prefix.rstrip("."), node)]
    if not isinstance(node, dict):
        return []
    return [
        pair for key, value in node.items() for pair in catalog_entries(value, f"{prefix}{key}.")
    ]


def _holds(catalog: dict, dotted: str) -> bool:
    node: object = catalog
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str)


def catalog_keys(node: object, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix.rstrip(".")}
    keys: set[str] = set()
    for key, value in node.items():
        keys |= catalog_keys(value, f"{prefix}{key}.")
    return keys


def main() -> int:
    if not SRC.is_dir():
        print(f"no frontend at {SRC}", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG.read_text())
    failures: list[str] = []
    absent: list[str] = []
    # Both catalog rules read `.ts` as well as `.tsx`, and read the `dev/` playground too.
    # The offence sweep skips both - a hook holds no JSX, and the playground's copy is not
    # the product's - but a key a hook reads is read, and one the playground reads is not
    # dead. Only tests are excluded on both counts: a test names the copy it asserts on.
    sources = [
        path
        for path in sorted(SRC.rglob("*.ts*"))
        if path.suffix in (".ts", ".tsx") and not path.name.endswith(SKIPPED_NAMES)
    ]
    for path in sources:
        relative = str(path.relative_to(ROOT))
        if path.suffix != ".tsx" or any(part in relative for part in SKIPPED_DIRS):
            continue
        for number, what in offences(path):
            failures.append(f"{relative}:{number}: {what}")
        for number, what in missing_keys(path, catalog):
            absent.append(f"{relative}:{number}: {what}")

    if failures:
        # `--all` for somebody working through a backlog; the default keeps a failing
        # build readable.
        shown = failures if "--all" in sys.argv else failures[:200]
        print(f"{len(failures)} hardcoded string(s). Every one belongs in messages/en.json:\n")
        for failure in shown:
            print(f"  {failure}")
        if len(failures) > len(shown):
            print(f"  … and {len(failures) - len(shown)} more (--all to list them)")
        print(
            "\nMove the string into the catalog and read it with useTranslations, or mark a\n"
            "genuine non-string with `i18n-exempt: <reason>` on the line or the one above."
        )
        return 1

    if absent:
        shown = absent if "--all" in sys.argv else absent[:200]
        print(f"{len(absent)} message(s) read but not in messages/en.json:\n")
        for one in shown:
            print(f"  {one}")
        if len(absent) > len(shown):
            print(f"  … and {len(absent) - len(shown)} more (--all to list them)")
        return 1

    unread = unread_keys(catalog, sources)
    if unread:
        shown = unread if "--all" in sys.argv else unread[:200]
        print(f"{len(unread)} message(s) in messages/en.json that nothing reads:\n")
        for one in shown:
            print(f"  {one}")
        if len(unread) > len(shown):
            print(f"  … and {len(unread) - len(shown)} more (--all to list them)")
        print(
            "\nDelete the key, or read it. A key nothing reads is a key a translator\n"
            "translates for nobody - and where a component kept the literal beside it,\n"
            "the English is still on screen in every locale."
        )
        return 1

    # The playground reads the catalog like anything else, so it counts above; what it
    # renders is not the product's copy, so it does not count here.
    duplicated = duplicated_in_source(
        catalog,
        [path for path in sources if not any(part in str(path) for part in SKIPPED_DIRS)],
    )
    if duplicated:
        shown = duplicated if "--all" in sys.argv else duplicated[:200]
        print(f"{len(duplicated)} message(s) also written out in the source:\n")
        for path, number, key, words in shown:
            print(f"  {path.relative_to(ROOT)}:{number}: {key} = {words!r}")
        if len(duplicated) > len(shown):
            print(f"  … and {len(duplicated) - len(shown)} more (--all to list them)")
        print("\nRead the key that already holds this sentence.")
        return 1

    keys = catalog_keys(catalog)
    print(f"No hardcoded copy in frontend/src. {len(keys)} messages in en.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
