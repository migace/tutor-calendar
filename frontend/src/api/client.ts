import type { components } from "./schema";

// Types come from the backend's OpenAPI document (`pnpm gen:api`), so a change
// to the API contract shows up here as a compile error, not a runtime surprise.
export type Slot = components["schemas"]["SlotOut"];
export type Tutor = components["schemas"]["TutorOut"];
export type SlotsResponse = components["schemas"]["SlotsResponse"];

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function fetchSlots(slug: string, signal?: AbortSignal): Promise<SlotsResponse> {
  const response = await fetch(`/api/v1/tutors/${encodeURIComponent(slug)}/slots`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed with status ${response.status}`);
  }
  return (await response.json()) as SlotsResponse;
}
