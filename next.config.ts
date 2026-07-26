import type { NextConfig } from "next";
import os from "os";
import path from "path";

const nextConfig: NextConfig = {
  serverExternalPackages: ["@prisma/client", "prisma", "exceljs", "xlsx", "pdf-parse", "jspdf", "pdf-lib", "tesseract.js", "sharp"],
  eslint: { ignoreDuringBuilds: true },
  // tesseract.js-core picks its .wasm binary at runtime via a computed fs path (feature-detected
  // SIMD support), not a string literal require — Vercel's build-time file tracer can't follow
  // that, so the .wasm never made it into the deployed function and OCR'd PDFs 500'd there ("ENOENT
  // ... tesseract-core-relaxedsimd.wasm") despite working locally. Force every variant along for
  // the two routes that actually parse uploaded files.
  outputFileTracingIncludes: {
    "/api/projects/**/*": ["./node_modules/tesseract.js-core/**/*.wasm*"],
  },
  experimental: {
    // Tree-shake lucide-react so only used icons are bundled.
    // On a network share this meaningfully cuts initial JS parse time.
    optimizePackageImports: ["lucide-react"],
    // Slow first-compiles over SMB (10-20s+) were exceeding the jest-worker child
    // process's retry limit ("Jest worker encountered N child process exceptions"),
    // which 500s whatever request triggered the compile — including uploads.
    // Compiling in-process (no forked workers) avoids that IPC/timeout entirely.
    cpus: 1,
    workerThreads: false,
  },
  webpack: (config) => {
    // storage/uploads and prisma/dev.db are written on every request — without this,
    // the dev watcher treats those writes as source changes and hot-reloads mid-response,
    // which aborts the in-flight fetch (surfaces client-side as "Failed to fetch").
    config.watchOptions = {
      ...config.watchOptions,
      // WAL mode (see lib/db.ts) touches dev.db-wal/-shm on every query, not just
      // dev.db itself — glob it explicitly, the trailing "dev.db*" wildcard alone
      // wasn't reliably excluding the sidecar files on this filesystem.
      ignored: [
        "**/node_modules/**",
        "**/.next/**",
        "**/storage/**",
        "**/reports/**",
        "**/.playwright-mcp/**",
        "**/prisma/dev.db",
        "**/prisma/dev.db-wal",
        "**/prisma/dev.db-shm",
        "**/prisma/dev.db-journal",
      ],
    };
    // the project lives on a network share (Z:\ / \\...\ia_bd\...) — webpack's
    // filesystem pack cache over SMB is unreliable and corrupts, which surfaces as
    // "RangeError: Failed to allocate memory" in PackFileCacheStrategy. Cache to
    // local disk instead.
    if (config.cache && typeof config.cache === "object" && config.cache.type === "filesystem") {
      config.cache.cacheDirectory = path.join(os.tmpdir(), "bdia-webpack-cache");
    }
    return config;
  },
};

export default nextConfig;
