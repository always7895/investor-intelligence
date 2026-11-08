import { defineConfig } from "vitest/config";

// Default run configuration (the opt-in live suite keeps vitest.task0-live.config.ts). The setup file isolates the Worker's per-isolate memory of verified
// lazy bodies between tests, because tests assert physical KV reads and tampered-blob refusals.
export default defineConfig({
  test: {
    setupFiles: ["test/helpers/reset-verified-lazy.ts"],
  },
});
