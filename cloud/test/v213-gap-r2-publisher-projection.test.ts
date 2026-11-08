/** F6: output of the real Python publisher projection, verified by the real Worker validator. */
import { describe, expect, it } from "vitest";
import { parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import projection from "./fixtures/gap-r2-publisher-projection.json";

describe("GAP-R2 13-layer publisher -> Worker contract", () => {
  it("accepts all thirteen projected layers including bounded robotics and display-only market window", () => {
    const payload: any = doc(Date.now() - HOUR);
    payload.industries = projection.industries;
    payload.market_window = projection.market_window;
    expect(payload.industries).toHaveLength(13);
    expect(payload.market_window).toEqual({
      positive_share: 0.5,
      median_ret_6m: 0.15000000000000002,
      count_used: 2,
      unknown_count: 1,
      scored_universe_count: 3,
    });
    const result = parseBottleneckV3(payload);
    expect(result).not.toBeNull();
    expect(result?.industries).toHaveLength(13);
    const robotics = result?.industries.find(row => row.id === "physical_ai_robotics");
    expect(robotics).toBeDefined();
    expect(robotics!.leopold_constraint.length).toBeLessThanOrEqual(120);
    expect((robotics!.leopold_constraint_zh ?? "").length).toBeLessThanOrEqual(50);
    expect(robotics!.chain).toBe("physical_ai_robotics");
  });

  it("enforces the real validIndustry string limits rather than silently truncating", () => {
    const payload: any = doc(Date.now() - HOUR);
    payload.industries = JSON.parse(JSON.stringify(projection.industries));
    const robot = payload.industries.find((row: { id: string }) => row.id === "physical_ai_robotics");
    robot.leopold_constraint = "X".repeat(301);
    expect(parseBottleneckV3(payload)).toBeNull();
    robot.leopold_constraint = "OK";
    robot.leopold_constraint_zh = "中".repeat(301);
    expect(parseBottleneckV3(payload)).toBeNull();
  });
});
