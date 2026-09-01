import v211Worker, { type V211Env } from "../v211/worker";
import { authenticateV21AdminRequest } from "../v21/admin";
import { ingestV213Top20Report } from "./admin";
import { broadcastV213Top20, scheduledV213Broadcast } from "./broadcast";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

async function handleV213Admin(request: Request, env: V211Env): Promise<Response> {
  try {
    const body = await authenticateV21AdminRequest(request, env);
    return jsonResponse({ status: "accepted", ...(await ingestV213Top20Report(body, env)) });
  } catch (error) {
    return jsonResponse(
      { ok: false, code: error instanceof Error ? error.message : "V213_ADMIN_FAILED" },
      401,
    );
  }
}

/**
 * v2.1.3 production entrypoint.
 *
 * All ordinary request behavior remains delegated to the accepted v2.1.2 owner
 * Worker, including the local-model QA route. Only the authenticated v2.1.3
 * report-ingest/test routes and scheduled seven-field owner broadcast are added.
 */
export default {
  async fetch(request: Request, env: V211Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/v213/admin/top20-report") {
      return handleV213Admin(request, env);
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/test-push") {
      try {
        await authenticateV21AdminRequest(request, env);
        return jsonResponse(await broadcastV213Top20(env, "test"));
      } catch (error) {
        return jsonResponse(
          { ok: false, code: error instanceof Error ? error.message : "V213_TEST_PUSH_FAILED" },
          401,
        );
      }
    }
    return v211Worker.fetch(request, env, ctx);
  },

  async scheduled(
    controller: ScheduledController,
    env: V211Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(
      scheduledV213Broadcast(env, controller.cron, controller.scheduledTime).then((result) => {
        if (!["sent", "duplicate", "disabled"].includes(String(result.status ?? ""))) {
          console.error("V213_SCHEDULED_BROADCAST_SKIPPED", String(result.status ?? "unknown"));
        }
      }),
    );
  },
} satisfies ExportedHandler<V211Env>;
