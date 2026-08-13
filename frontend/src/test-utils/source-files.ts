import { readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * Every file under `dir`, recursively, whose basename passes `filter`.
 *
 * The one walker behind the repository's source sweeps — the tests that read
 * every file under `src/` and assert a pattern appears nowhere (or everywhere).
 * Three of them each hand-rolled this and had already drifted apart before the
 * third landed, which is how a sweep quietly reads fewer files than its author
 * thinks (#618). Deliberately outside the coverage `include` list in
 * `vitest.config.ts`, so a test helper does not drag the 100% gate along.
 */
export function sourceFiles(dir: string, filter: (name: string) => boolean): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path, filter);
    return filter(entry.name) ? [path] : [];
  });
}
