import { build } from "esbuild";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const runtime = await mkdtemp(join(tmpdir(), "project-atlas-performance-local-v5-review-"));
const output = join(runtime, "bundle.cjs");

try {
  await build({
    entryPoints: [join(root, "tests", "performance-local-v5-review.test.tsx")],
    absWorkingDir: root,
    outfile: output,
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    define: {
      "import.meta.env.VITE_API_BASE_URL": '"http://localhost:8000"',
    },
    logLevel: "silent",
  });
  const result = spawnSync(process.execPath, ["--test", output], {
    cwd: root,
    stdio: "inherit",
  });
  process.exitCode = result.status ?? 1;
} finally {
  await rm(runtime, { recursive: true, force: true });
}
