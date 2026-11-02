// @vitest-environment node
import { execFile } from "node:child_process";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";

const execute = promisify(execFile);

test.each([false, true])(
  "merged coverage preserves the gate (uncovered function: %s)",
  async (uncovered) => {
    const root = process.cwd();
    const fixture = await mkdtemp(path.join(tmpdir(), "agenticos-coverage-"));
    const command = path.join(root, "node_modules/vitest/vitest.mjs");
    const env = { ...process.env };
    delete env.VITEST_SHARD;
    delete env.NODE_V8_COVERAGE;
    try {
      await symlink(path.join(root, "node_modules"), path.join(fixture, "node_modules"), "dir");
      await writeFile(path.join(fixture, "package.json"), '{"type":"module"}');
      await writeFile(
        path.join(fixture, "subject.ts"),
        "export const a = () => 1; export const b = () => 2;" +
          (uncovered ? "export const uncovered = () => 3;" : ""),
      );
      for (const [index, name] of ["a", "b"].entries()) {
        await writeFile(
          path.join(fixture, `${name}.test.ts`),
          `import { test, expect } from "vitest"; import { ${name} } from "./subject";` +
            `test("${name}", () => expect(${name}()).toBe(${index + 1}));`,
        );
      }
      // Reuse the real thresholds and shard switch, with only the workload replaced.
      await writeFile(
        path.join(fixture, "vitest.config.ts"),
        `import base from ${JSON.stringify(path.join(root, "vitest.config.ts"))};` +
          `export default {...base, test: {...base.test, environment: "node", setupFiles: [],` +
          `include: ["*.test.ts"], coverage: {...base.test.coverage,` +
          `include: ["subject.ts"], reporter: ["json"]}}};`,
      );
      for (const shard of [1, 2]) {
        await execute(
          process.execPath,
          [command, "run", "--coverage", `--shard=${shard}/2`, "--reporter=blob", "--maxWorkers=1"],
          { cwd: fixture, env: { ...env, VITEST_SHARD: "true" }, timeout: 30_000 },
        );
      }
      const merge = execute(
        process.execPath,
        [command, "--merge-reports=.vitest-reports", "--coverage"],
        { cwd: fixture, env, timeout: 30_000 },
      );
      if (uncovered) {
        await expect(merge).rejects.toMatchObject({ code: 1 });
      } else {
        await expect(merge).resolves.toMatchObject({ stderr: expect.any(String) });
      }
    } finally {
      await rm(fixture, { recursive: true, force: true });
    }
  },
  90_000,
);
