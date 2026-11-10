// Replay diagnostics only: a refused, expired legacy report never renews data or publication authority.
import { readV213BottleneckReport } from "../../src/v213/bottleneck-report";
import { hasVerifiedSnapshotCustody, type PublicSnapshotView } from "../../src/v213/public-snapshot";
import { v213ReportMaxAgeSeconds } from "../../src/v213/report-age";
import { readV213Top20Report, v213TimesAreFresh, type V213Top20Env } from "../../src/v213/top20-report";

export interface LegacyReportProbe {
  readonly expiredRefused: boolean;
  readonly originalGeneratedAt: string | null;
  readonly pipelineFresh: boolean;
}

export async function probeLegacyReport(
  view: PublicSnapshotView, env: Pick<V213Top20Env, "V21_TOP20_MAX_AGE_SECONDS">,
  actualReaderResult: unknown, observedAt = Date.now(),
): Promise<LegacyReportProbe> {
  if (!hasVerifiedSnapshotCustody(view, "v213:top20-report:latest")) {
    return { expiredRefused: false, originalGeneratedAt: null, pipelineFresh: false };
  }
  const pipelineFresh = v213TimesAreFresh(env, [await view.text(["last_successful_pipeline_timestamp"])], observedAt);
  const bottleneck = await readV213BottleneckReport(view);
  const legacy = bottleneck?.status === "QUALIFIED" && bottleneck.records.length > 0 ? bottleneck : await readV213Top20Report(view);
  const originalGeneratedAt = legacy?.generated_at ?? null;
  const age = originalGeneratedAt === null ? NaN : (observedAt - Date.parse(originalGeneratedAt)) / 1000;
  const expiredRefused = !!view.sealRunId && view.runId !== view.sealRunId && pipelineFresh
    && Number.isFinite(age) && age > v213ReportMaxAgeSeconds()
    && typeof actualReaderResult === "string" && actualReaderResult.length > 0;
  return { expiredRefused, originalGeneratedAt, pipelineFresh };
}
