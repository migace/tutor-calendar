import type { Slot } from "../../api/client";

export interface DayGroup {
  /** Calendar day in the display time zone, as YYYY-MM-DD. */
  day: string;
  slots: Slot[];
}

/**
 * Groups slots by the calendar day they fall on *in the given time zone*.
 *
 * The API returns UTC instants. Which day an instant belongs to depends on who
 * is looking: 23:30 UTC on Monday is already Tuesday in Warsaw.
 */
export function groupSlotsByDay(slots: readonly Slot[], timeZone: string): DayGroup[] {
  // en-CA formats dates as YYYY-MM-DD, which also sorts correctly as text.
  const dayOf = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

  const groups: DayGroup[] = [];
  for (const slot of slots) {
    const day = dayOf.format(new Date(slot.start));
    const last = groups.at(-1);
    if (last?.day === day) {
      last.slots.push(slot);
    } else {
      groups.push({ day, slots: [slot] });
    }
  }
  return groups;
}
