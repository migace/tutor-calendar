import { UI_LOCALE } from "./i18n";

/**
 * Formats a calendar date from the API ("2026-11-16").
 *
 * Such a date has no time zone: it is a square on someone's calendar. Parsing
 * it as local midnight would show the day before to anyone west of the server,
 * so it is read and formatted as UTC, where it cannot shift.
 */
export function formatDay(date: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(UI_LOCALE, { ...options, timeZone: "UTC" }).format(
    new Date(`${date}T00:00:00Z`),
  );
}

/** "Tuesday 17 November, 15:00–16:00" for an instant range, in the given zone. */
export function formatLesson(lesson: { start: string; end: string }, timeZone: string): string {
  const day = new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone,
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(lesson.start));
  const time = new Intl.DateTimeFormat(UI_LOCALE, { timeZone, hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time.formatRange(new Date(lesson.start), new Date(lesson.end))}`;
}

/** "Monday 16 November, 15:00" for a single instant, in the given zone. */
export function formatMoment(instant: string, timeZone: string): string {
  return new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone,
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(instant));
}

/**
 * Lesson time for people: "10 h", "1 h 30 min", "45 min", and "−1 h" for time owed.
 * The minus is the typographic one, which screen readers announce as "minus".
 */
export function formatMinutes(minutes: number): string {
  const total = Math.abs(minutes);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  const parts = [hours > 0 && `${hours} h`, (rest > 0 || hours === 0) && `${rest} min`];
  return `${minutes < 0 ? "−" : ""}${parts.filter(Boolean).join(" ")}`;
}
