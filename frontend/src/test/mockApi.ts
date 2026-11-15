import { vi } from "vitest";

export function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface Call {
  method: string;
  /** Path with its query string, e.g. "/api/v1/me/week?date=2026-11-23". */
  url: string;
  body: unknown;
}

type Reply = (call: Call) => Response | Promise<Response>;

/**
 * A stand-in for the API. Keys are "METHOD /path" without the query string.
 * A list of replies is served in order, the last one for ever.
 */
export function mockApi(routes: Record<string, Reply | Reply[]>) {
  const queues = new Map(
    Object.entries(routes).map(([route, reply]) => [route, Array.isArray(reply) ? [...reply] : [reply]]),
  );
  const calls: Call[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const call: Call = { method, url, body: init?.body ? JSON.parse(String(init.body)) : null };
      calls.push(call);

      const queue = queues.get(`${method} ${url.split("?")[0]}`);
      if (!queue) throw new Error(`unexpected request: ${method} ${url}`);
      const reply = queue.length > 1 ? queue.shift()! : queue[0]!;
      return reply(call);
    }),
  );

  return {
    calls,
    callsTo: (route: string) =>
      calls.filter((call) => `${call.method} ${call.url.split("?")[0]}` === route),
  };
}
