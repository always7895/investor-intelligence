import { defineConfig } from "vitest/config";

// TASK0 Phase-1F: opt-in manual live-gateway suite.
// The default `vitest run` never includes anything here; this config is only
// invoked after the operator explicitly expects the real local model to run.
export default defineConfig({
  test: {
    include: ["test/manual/**/*.manual.ts"],
    environment: "node",
    testTimeout: 300_000,
    hookTimeout: 240_000,
  },
});