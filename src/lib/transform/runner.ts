import { spawn } from "child_process";
import path from "path";
import { prisma } from "@/lib/db";

/**
 * Executes a pipeline script and streams its stdout/stderr into the
 * TransformRun log so the UI can show it live. The script itself owns all
 * business logic; this only orchestrates execution.
 *
 * No output file is produced or persisted — the log plus the script's own
 * BigQuery upload are the only outputs.
 */
export function startTransformRun(runId: string, scriptFile: string, args: string[]): void {
  void runTransformAndWait(runId, scriptFile, args);
}

/** Same as startTransformRun but resolves when the script exits (true = success). */
export function runTransformAndWait(runId: string, scriptFile: string, args: string[]): Promise<boolean> {
  const python = process.env.PYTHON_BIN || "python";
  const scriptPath = path.join(process.cwd(), "scripts", scriptFile);

  let log = "";
  let timer: NodeJS.Timeout | null = null;
  const flush = async (extra?: { status?: string }) => {
    timer = null;
    await prisma.transformRun
      .update({ where: { id: runId }, data: { log, ...(extra?.status ? { status: extra.status } : {}) } })
      .catch(() => null);
  };
  const scheduleFlush = () => {
    if (!timer) timer = setTimeout(() => void flush(), 500);
  };
  const append = (chunk: Buffer | string) => {
    log += chunk.toString();
    // ponytail: cap kept log at 2 MB (drop oldest); raise if pipelines ever log more
    if (log.length > 2_000_000) log = log.slice(log.length - 2_000_000);
    scheduleFlush();
  };

  return new Promise<boolean>((resolve) => {
    const child = spawn(python, ["-u", scriptPath, ...args], {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });

    let settled = false;
    const finish = async (ok: boolean, status: string) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      await flush({ status });
      resolve(ok);
    };

    child.stdout.on("data", append);
    child.stderr.on("data", append);
    child.on("error", (err) => {
      append(`\n[runner] Could not start Python (${python}): ${err.message}\n` +
        `[runner] Install Python 3 and the script dependencies, or set PYTHON_BIN to the interpreter path.\n` +
        `[runner] No local Python? Run this pipeline in Google Colab instead — see the "Menjalankan pipeline di Google Colab" section in README.md.\n`);
      void finish(false, "FAILED");
    });
    child.on("close", (code) => {
      append(`\n[runner] Process exited with code ${code}\n`);
      void finish(code === 0, code === 0 ? "COMPLETED" : "FAILED");
    });
  });
}
