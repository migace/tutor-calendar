import type { components } from "./schema";

// Types come from the backend's OpenAPI document (`pnpm gen:api`), so a change
// to the API contract shows up here as a compile error, not a runtime surprise.
export type Slot = components["schemas"]["SlotOut"];
export type Tutor = components["schemas"]["TutorOut"];
export type SlotsResponse = components["schemas"]["SlotsResponse"];
export type BookingRequest = components["schemas"]["BookingIn"];
export type Booking = components["schemas"]["BookingOut"];
export type Profile = components["schemas"]["ProfileOut"];
export type Week = components["schemas"]["WeekOut"];
export type Lesson = components["schemas"]["LessonOut"];
export type Availability = components["schemas"]["AvailabilityOut"];
export type WeeklyRule = components["schemas"]["WeeklyRuleModel"];
export type ManagedBooking = components["schemas"]["ManagedBookingOut"];
export type Series = components["schemas"]["SeriesOut"];
export type SeriesPlan = components["schemas"]["SeriesIn"];

export class ApiError extends Error {
  readonly status: number;
  /** The server's own explanation, when it gave one in plain words. */
  readonly detail: string | null;
  /** The whole error body, for the few errors that carry more than a sentence. */
  readonly body: unknown;

  constructor(status: number, message: string, detail: string | null = null, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

function tutorUrl(slug: string, resource: string): string {
  return `/api/v1/tutors/${encodeURIComponent(slug)}/${resource}`;
}

async function fail(response: Response): Promise<never> {
  // Validation errors carry a list in `detail`; only a plain sentence is worth showing.
  const body: unknown = await response.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  throw new ApiError(
    response.status,
    `Request failed with status ${response.status}`,
    typeof detail === "string" ? detail : null,
    body,
  );
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) return fail(response);
  return (await response.json()) as T;
}

const JSON_BODY = { Accept: "application/json", "Content-Type": "application/json" };

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

/** Asks for a sign-in link. Resolves the same way whether or not the address is known. */
export async function requestSignInLink(email: string): Promise<void> {
  const response = await fetch("/api/v1/auth/links", {
    method: "POST",
    headers: JSON_BODY,
    body: JSON.stringify({ email }),
  });
  if (!response.ok) await fail(response);
}

/** Trades the token from a sign-in link for a session cookie. */
export async function signIn(token: string): Promise<Profile> {
  const response = await fetch("/api/v1/auth/session", {
    method: "POST",
    headers: JSON_BODY,
    body: JSON.stringify({ token }),
  });
  return parse<Profile>(response);
}

export async function signOut(): Promise<void> {
  const response = await fetch("/api/v1/auth/session", { method: "DELETE" });
  if (!response.ok) await fail(response);
}

/** The signed-in tutor, or null when nobody is signed in. */
export async function fetchProfile(signal?: AbortSignal): Promise<Profile | null> {
  const response = await fetch("/api/v1/me", { headers: { Accept: "application/json" }, signal });
  if (response.status === 401) return null;
  return parse<Profile>(response);
}

/** The tutor's week containing `date` (YYYY-MM-DD), or the current week. */
export async function fetchWeek(date: string | null, signal?: AbortSignal): Promise<Week> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  const response = await fetch(`/api/v1/me/week${query}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  return parse<Week>(response);
}

export async function fetchAvailability(signal?: AbortSignal): Promise<Availability> {
  const response = await fetch("/api/v1/me/availability", {
    headers: { Accept: "application/json" },
    signal,
  });
  return parse<Availability>(response);
}

export async function saveAvailability(rules: WeeklyRule[]): Promise<Availability> {
  const response = await fetch("/api/v1/me/availability", {
    method: "PUT",
    headers: JSON_BODY,
    body: JSON.stringify({ rules }),
  });
  return parse<Availability>(response);
}

const withManageToken = (token: string) => ({
  Accept: "application/json",
  // In a header, not the address, so the token stays out of server logs.
  Authorization: `Bearer ${token}`,
});

/** The booking a manage token belongs to, as the student who made it sees it. */
export async function fetchManagedBooking(
  token: string,
  signal?: AbortSignal,
): Promise<ManagedBooking> {
  const response = await fetch("/api/v1/booking", { headers: withManageToken(token), signal });
  return parse<ManagedBooking>(response);
}

export async function cancelManagedBooking(token: string): Promise<ManagedBooking> {
  const response = await fetch("/api/v1/booking", {
    method: "DELETE",
    headers: withManageToken(token),
  });
  return parse<ManagedBooking>(response);
}

/** What a tutor can do to one of their lessons. */
export async function changeLesson(
  lessonId: string,
  change: "cancellation" | "no-show",
): Promise<Lesson> {
  const response = await fetch(`/api/v1/me/lessons/${encodeURIComponent(lessonId)}/${change}`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return parse<Lesson>(response);
}

export async function fetchSeries(signal?: AbortSignal): Promise<Series[]> {
  const response = await fetch("/api/v1/me/series", {
    headers: { Accept: "application/json" },
    signal,
  });
  return parse<Series[]>(response);
}

/**
 * Books a weekly series under an id the caller chose. Sending the same plan
 * with the same id again returns the series the first attempt created.
 */
export async function startSeries(seriesId: string, plan: SeriesPlan): Promise<Series> {
  const response = await fetch(`/api/v1/me/series/${encodeURIComponent(seriesId)}`, {
    method: "PUT",
    headers: JSON_BODY,
    body: JSON.stringify(plan),
  });
  return parse<Series>(response);
}

/** Days ("YYYY-MM-DD") on which a refused series clashed with existing lessons. */
export function conflictsIn(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const conflicts = (error.body as { conflicts?: unknown } | null)?.conflicts;
  return Array.isArray(conflicts) ? conflicts.map(String) : null;
}

export async function endSeries(seriesId: string): Promise<Series> {
  const response = await fetch(`/api/v1/me/series/${encodeURIComponent(seriesId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  return parse<Series>(response);
}
