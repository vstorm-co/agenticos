/**
 * Collect the licence files the frontend image owes its recipients.
 *
 * Next's standalone output traces JavaScript and `package.json` only, so an image
 * built from it ships MIT and LGPL code with none of the licence files those
 * licences require to travel with copies. This runs in the builder stage, after
 * `bun install`, and writes into one directory that the runner stage copies:
 *
 * - every `LICENSE*`, `LICENCE*` and `COPYING*` file of every package in the
 *   production closure of `package.json`, under the package's own path
 *   (`<out>/node_modules/<name>/LICENSE`), so a reader of the image finds the
 *   text where the code is;
 * - for a package that publishes no such file, a `NOTICE` at the same path naming
 *   the package, its version, its declared licence, its author and its
 *   repository - the attribution the package itself made available - and beside
 *   it the text of each licence in its expression, from `licenses/texts/`. A
 *   licence with no text there fails the build: `@img/sharp-libvips-linux-*`
 *   ships an LGPL library with no copy of the LGPL, and an image that did the same
 *   would be the defect this script exists to close. `client-only` names no author
 *   at all; `licenses/policy.toml` in the repository records the copyright holder
 *   for it and `THIRD_PARTY_NOTICES.md` carries the line;
 * - the frontend's own `NOTICE` (the brand-mark attributions) and the fonts'
 *   `OFL.txt`, at the top of the directory.
 *
 * The closure is walked the way `require` resolves: dependencies, optional
 * dependencies and installed peers, from the dependant's own directory upwards,
 * so a nested copy of a package is found beside the dependant that needed it.
 * What is installed here is already what bun resolved for this platform, so
 * nothing is filtered by `os` or `cpu`. A production dependency that is not
 * installed is an error: the closure of something other than the lockfile is
 * not what the image ships.
 *
 * `scripts/license_inventory.py` in the repository is the other half - the review
 * of what these licences oblige - and reads the same tree with the same walk.
 */

import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

const LICENSE_FILE = /^(licen[cs]e|copying)/i;
const TEXTS = join("licenses", "texts");

interface Manifest {
  readonly name: string;
  readonly version: string;
  readonly license?: unknown;
  readonly licenses?: unknown;
  readonly author?: unknown;
  readonly contributors?: unknown;
  readonly repository?: unknown;
  readonly dependencies?: Record<string, string>;
  readonly optionalDependencies?: Record<string, string>;
  readonly peerDependencies?: Record<string, string>;
}

/** One package the image ships, and where its licence text came from. */
export interface Collected {
  readonly name: string;
  readonly version: string;
  /** Licence files copied, relative to the package directory; empty when a NOTICE was written instead. */
  readonly files: readonly string[];
}

function readManifest(path: string): Manifest {
  return JSON.parse(readFileSync(path, "utf8")) as Manifest;
}

/** `node_modules/<name>/package.json` as `require` would find it from `from`. */
export function resolvePackage(name: string, from: string, root: string): string | undefined {
  let directory = from;
  for (;;) {
    const candidate = join(directory, "node_modules", name, "package.json");
    if (existsSync(candidate)) return candidate;
    if (directory === root) return undefined;
    directory = dirname(directory);
  }
}

function person(value: unknown): string | undefined {
  if (typeof value === "string") return value.trim() || undefined;
  if (value && typeof value === "object" && "name" in value && typeof value.name === "string") {
    const email = "email" in value && typeof value.email === "string" ? ` <${value.email}>` : "";
    return `${value.name}${email}`;
  }
  return undefined;
}

function declaredLicense(manifest: Manifest): string {
  const field = manifest.license;
  if (typeof field === "string" && field.trim()) return field.trim();
  if (field && typeof field === "object" && "type" in field && typeof field.type === "string")
    return field.type;
  if (Array.isArray(manifest.licenses)) {
    const types = manifest.licenses
      .map((entry: unknown) =>
        entry && typeof entry === "object" && "type" in entry ? entry.type : entry,
      )
      .filter((type): type is string => typeof type === "string");
    if (types.length) return types.join(" OR ");
  }
  return "not declared";
}

/** The SPDX identifiers in a licence expression, without operators, exceptions or parentheses. */
export function identifiers(expression: string): string[] {
  const found: string[] = [];
  let skip = false;
  for (const token of expression.split(/[\s()]+/).filter(Boolean)) {
    if (skip) {
      skip = false;
      continue;
    }
    if (token.toUpperCase() === "WITH") {
      skip = true;
      continue;
    }
    if (token.toUpperCase() === "AND" || token.toUpperCase() === "OR") continue;
    if (!found.includes(token)) found.push(token);
  }
  return found;
}

function repositoryUrl(manifest: Manifest): string | undefined {
  const repository = manifest.repository;
  const url =
    repository && typeof repository === "object" && "url" in repository
      ? repository.url
      : repository;
  return typeof url === "string" && url.trim() ? url.trim() : undefined;
}

/**
 * The attribution a package without a licence file made available about itself.
 *
 * Returned as the lines of a NOTICE file rather than written, so the same text can
 * be asserted on. `contributors` is read when `author` is absent: a package with
 * either has somebody to name, and the review in the repository refuses one with
 * neither unless a person recorded the holder.
 */
export function noticeFor(manifest: Manifest): string {
  const lines = [
    `${manifest.name} ${manifest.version}`,
    `Licence: ${declaredLicense(manifest)}`,
    "",
    "This package publishes no licence file. The copyright holders it names:",
  ];
  const author = person(manifest.author);
  const contributors = Array.isArray(manifest.contributors)
    ? manifest.contributors.map(person).filter((name): name is string => name !== undefined)
    : [];
  const holders = author ? [author, ...contributors] : contributors;
  lines.push(
    ...(holders.length
      ? holders.map((holder) => `  ${holder}`)
      : ["  (none named in package.json)"]),
  );
  const repository = repositoryUrl(manifest);
  if (repository) lines.push("", `Source: ${repository}`);
  return `${lines.join("\n")}\n`;
}

/**
 * Walk the production closure under `root` and write the licence directory at `out`.
 *
 * Returns what was collected, sorted by name and version, so a caller can print or
 * assert on it.
 */
export function collect(root: string, out: string): Collected[] {
  const manifest = readManifest(join(root, "package.json"));
  const pending: Array<{ name: string; from: string; optional: boolean }> = [];
  for (const name of Object.keys(manifest.dependencies ?? {}))
    pending.push({ name, from: root, optional: false });
  for (const name of Object.keys(manifest.optionalDependencies ?? {}))
    pending.push({ name, from: root, optional: true });
  const seen = new Set<string>();
  const collected: Collected[] = [];
  mkdirSync(out, { recursive: true });

  while (pending.length) {
    const { name, from, optional } = pending.pop()!;
    const manifestPath = resolvePackage(name, from, root);
    if (manifestPath === undefined) {
      if (optional) continue;
      throw new Error(`${name} is a production dependency and is not installed under ${root}`);
    }
    const packageDir = dirname(manifestPath);
    const key = relative(root, packageDir);
    if (seen.has(key)) continue;
    seen.add(key);

    const dependant = readManifest(manifestPath);
    const target = join(out, key);
    mkdirSync(target, { recursive: true });
    const files = readdirSync(packageDir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && LICENSE_FILE.test(entry.name))
      .map((entry) => entry.name)
      .sort();
    for (const file of files) copyFileSync(join(packageDir, file), join(target, file));
    if (!files.length) {
      writeFileSync(join(target, "NOTICE"), noticeFor(dependant));
      for (const id of identifiers(declaredLicense(dependant))) {
        const text = join(root, TEXTS, `${id}.txt`);
        if (!existsSync(text)) {
          throw new Error(
            `${dependant.name}@${dependant.version} ships no licence file and ${TEXTS}/${id}.txt does not exist; ` +
              "add the text so the image can carry it",
          );
        }
        copyFileSync(text, join(target, `LICENSE-${id}.txt`));
      }
    }
    collected.push({ name: dependant.name, version: dependant.version, files });

    for (const dep of Object.keys(dependant.dependencies ?? {}))
      pending.push({ name: dep, from: packageDir, optional: false });
    for (const dep of Object.keys(dependant.optionalDependencies ?? {}))
      pending.push({ name: dep, from: packageDir, optional: true });
    for (const peer of Object.keys(dependant.peerDependencies ?? {})) {
      if (resolvePackage(peer, packageDir, root) !== undefined)
        pending.push({ name: peer, from: packageDir, optional: true });
    }
  }

  for (const own of ["NOTICE", join("src", "app", "fonts", "OFL.txt")]) {
    const source = join(root, own);
    if (!existsSync(source))
      throw new Error(`${own} is missing from ${root}; the image would ship without it`);
    copyFileSync(source, join(out, own.split("/").pop()!));
  }

  return collected.sort(
    (a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version),
  );
}

function main(argv: string[]): number {
  const out = argv[0];
  if (!out) {
    console.error("usage: bun run scripts/collect-licenses.ts <output directory>");
    return 2;
  }
  const collected = collect(ROOT, out);
  const noticed = collected.filter((entry) => !entry.files.length);
  console.log(
    `${collected.length} packages; ${collected.length - noticed.length} shipped a licence file, ` +
      `${noticed.length} attributed from package.json: ${noticed.map((entry) => entry.name).join(", ") || "none"}`,
  );
  return 0;
}

const entry = process.argv[1];
if (entry !== undefined && import.meta.url === pathToFileURL(entry).href) {
  process.exit(main(process.argv.slice(2)));
}
