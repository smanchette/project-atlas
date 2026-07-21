import { build } from "esbuild";
import { randomUUID } from "node:crypto";
import { mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const runtime = join(root, ".test-runtime");
const output = join(runtime, `project-atlas-renewal-${randomUUID()}.cjs`);
try {
  await mkdir(runtime, { recursive: true });
  await build({
    entryPoints: ["tests/bootstrap-backup-renewal.test.tsx"],
    absWorkingDir: root,
    outfile: output,
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    define: { "import.meta.env.VITE_API_BASE_URL": '"http://localhost:8000"' },
    logLevel: "silent",
  });
  const result = spawnSync(process.execPath, ["--test", output], { stdio: "inherit" });
  process.exitCode = result.status ?? 1;
} finally {
  await rm(runtime, { recursive: true, force: true });
}
