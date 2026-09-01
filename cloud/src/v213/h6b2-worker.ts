import v21Worker, { type V21Env } from "../v21/worker";
import { authenticateV21AdminRequest } from "../v21/admin";
import { sendH6B2SevenFieldTestPush } from "./h6b2-line-test-push";

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

async function handleH6B2(request: Request, env: V21Env): Promise<Response> {
  try {
    const body = await authenticateV21AdminRequest(request, env);
    return jsonResponse(await sendH6B2SevenFieldTestPush(env, body));
  } catch (error) {
    return jsonResponse(
      { ok: false, code: error instanceof Error ? error.message : "H6B2_LINE_TEST_FAILED" },
      401,
    );
  }
}

/**
 * Temporary H6B2 acceptance entrypoint.
 *
 * Only the signed /v21/admin/v213-test-push route and a non-sensitive readiness
 * probe are added. Every other fetch route and both scheduled broadcasts
 * delegate to the already accepted v2.1 owner Worker. The H6B2 Windows runner
 * rolls this deployment back immediately after the one real owner LINE push.
 */
export default {
  async fetch(request: Request, env: V21Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/h6b2/ready") {
      return jsonResponse({
        ok: true,
        stage: "H6B2_REAL_LINE_SEVEN_FIELD_TEST",
        accepted_source_sha: "f1d6790de99c8af981a40e26993a12a444b214ba",
        accepted_preview_sha256: "ff0e0cfad5fffb6f0ed9c1482bc145f3ced7722f5eb571488e82a4f7b979c2c9",
        order_reconciliation: "R15_ORDER_ONLY",
        scheduled_worker_delegated: true,
      });
    }
    if (request.method === "POST" && url.pathname === "/v21/admin/v213-test-push") {
      return handleH6B2(request, env);
    }
    return v21Worker.fetch(request, env, ctx);
  },

  async scheduled(
    controller: ScheduledController,
    env: V21Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    return v21Worker.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<V21Env>;
