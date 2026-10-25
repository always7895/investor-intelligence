import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveApprovedPython } from "./helpers/task0-general-qa-harness";

/** Offline: the approved interpreter must be named explicitly and fails closed. */
describe("TASK0 approved python resolution (offline)", () => {
  afterEach(() => { vi.unstubAllEnvs(); });

  it("fails closed when II_TASK0_PYTHON_EXE is unset", () => {
    vi.stubEnv("II_TASK0_PYTHON_EXE", "x");
    delete process.env.II_TASK0_PYTHON_EXE; // unstubAllEnvs restores the pre-test value
    expect(() => resolveApprovedPython()).toThrow(/TASK0_APPROVED_PYTHON_UNSET/);
  });

  it("fails closed when II_TASK0_PYTHON_EXE is blank", () => {
    vi.stubEnv("II_TASK0_PYTHON_EXE", "  ");
    expect(() => resolveApprovedPython()).toThrow(/TASK0_APPROVED_PYTHON_UNSET/);
  });

  it("rejects a path that does not exist", () => {
    vi.stubEnv("II_TASK0_PYTHON_EXE", "nonexistent-dir-for-test/python-missing.exe");
    expect(() => resolveApprovedPython()).toThrow(/TASK0_APPROVED_PYTHON_MISSING/);
  });

  it("returns an existing executable unchanged", () => {
    vi.stubEnv("II_TASK0_PYTHON_EXE", process.execPath);
    expect(resolveApprovedPython()).toBe(process.execPath);
  });
});
