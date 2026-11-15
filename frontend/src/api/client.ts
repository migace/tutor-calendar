import type { components } from "./schema";

// Types come from the backend's OpenAPI document (`pnpm gen:api`), so a change
// to the API contract shows up here as a compile error, not a runtime surprise.
export type Slot = components["schemas"]["SlotOut"];
export type Tutor = components["schemas"]["TutorOut"];
export type SlotsResponse = components["schemas"]["SlotsResponse"];
export type BookingRequest = components["schemas"]["BookingIn"];
export type Booking = components["schemas"]["BookingOut"];

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function tutorUrl(slug: string, resource: string): string {
  return `/api/v1/tutors/${encodeURIComponent(slug)}/${resource}`;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchSlots(slug: string, signal?: AbortSignal): Promise<SlotsResponse> {
  const response = await fetch(tutorUrl(slug, "slots"), {
    headers: { Accept: "application/json" },
    signal,
  });
  return parse<SlotsResponse>(response);
}

/**
 * Books a lesson. Sending the same request again with the same key is safe: the
 * server returns the booking the first attempt created instead of a second one.
 */
export async function createBooking(
  slug: string,
  booking: BookingRequest,
  idempotencyKey: string,
): Promise<Booking> {
  const response = await fetch(tutorUrl(slug, "bookings"), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(booking),
  });
  return parse<Booking>(response);
}
