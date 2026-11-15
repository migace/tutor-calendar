interface TimeSpan {
  start: string;
  end: string;
}

/** "Tuesday 17 November, 15:00–16:00", in the given zone. */
export function describeSlot(slot: TimeSpan, timeZone: string, locale: string): string {
  const day = new Intl.DateTimeFormat(locale, {
    timeZone,
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(slot.start));
  const time = new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time.formatRange(new Date(slot.start), new Date(slot.end))}`;
}
