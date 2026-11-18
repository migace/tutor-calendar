import { useMemo, useState } from "react";

import type { Slot } from "../../api/client";
import { formatDate, formatDay, formatTime } from "../../dates";
import { useT } from "../../i18n";
import { groupSlotsByDay, type DayGroup } from "./groupSlotsByDay";

interface SlotPickerProps {
  slots: readonly Slot[];
  /** IANA zone the times are displayed in. */
  timeZone: string;
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
}

const DAY_MS = 86_400_000;

/** "2026-11-16" plus a number of days, without leaving UTC. */
function addDays(day: string, days: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** 0 for Monday … 6 for Sunday. */
function weekdayIndex(day: string): number {
  return (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
}

/** Every day from the Monday before the first free day to the Sunday after the last. */
function calendarDays(groups: readonly DayGroup[]): string[] {
  const first = groups[0]!.day;
  const last = groups.at(-1)!.day;
  const days: string[] = [];
  for (let day = addDays(first, -weekdayIndex(first)); day <= last || weekdayIndex(day) !== 0; ) {
    days.push(day);
    day = addDays(day, 1);
  }
  return days;
}

/** "November 2026", or "November – December 2026" when the days run into the next month. */
function describeMonths(first: string, last: string): string {
  const year = { year: "numeric" } as const;
  if (first.slice(0, 7) === last.slice(0, 7)) return formatDay(first, { month: "long", ...year });
  const from = formatDay(first, { month: "long" });
  return `${from} – ${formatDay(last, { month: "long", ...year })}`;
}

/**
 * A month calendar of the days with free times, and the times of one of them.
 *
 * Only days with times are buttons; the rest of the grid is there to show the
 * shape of the week and is hidden from screen readers.
 */
export function SlotPicker({ slots, timeZone, selected, onSelect }: SlotPickerProps) {
  const t = useT().booking;
  const groups = useMemo(() => groupSlotsByDay(slots, timeZone), [slots, timeZone]);
  const dayOf = (slot: Slot | null) =>
    slot && groups.find((group) => group.slots.some((s) => s.start === slot.start))?.day;
  const [chosen, setChosen] = useState(() => dayOf(selected) ?? groups[0]?.day);
  // A day whose last time was just taken is no longer offered.
  const current = groups.find((group) => group.day === chosen) ?? groups[0];
  if (!current) return null;

  const byDay = new Map(groups.map((group) => [group.day, group]));
  const grid = calendarDays(groups);
  const heading = formatDate(current.slots[0]!.start, timeZone);
  const headingId = `day-${current.day}`;

  return (
    <div className="picker">
      <div className="calendar">
        <p className="calendar__month">{describeMonths(groups[0]!.day, groups.at(-1)!.day)}</p>
        <div className="calendar__weekdays" aria-hidden="true">
          {grid.slice(0, 7).map((day) => (
            <span key={day}>{formatDay(day, { weekday: "short" }).replace(/\.$/, "")}</span>
          ))}
        </div>
        <div className="calendar__days" role="group" aria-label={t.pickDay}>
          {grid.map((day) => {
            const group = byDay.get(day);
            const number = formatDay(day, { day: "numeric" });
            if (!group) {
              return (
                <span key={day} className="calendar__day calendar__day--off" aria-hidden="true">
                  {number}
                </span>
              );
            }
            return (
              <button
                key={day}
                type="button"
                className="calendar__day"
                aria-pressed={day === current.day}
                aria-label={`${formatDate(group.slots[0]!.start, timeZone)}, ${t.freeTimes(group.slots.length)}`}
                onClick={() => setChosen(day)}
              >
                {number}
                <span className="calendar__dot" aria-hidden="true" />
              </button>
            );
          })}
        </div>
      </div>

      <section className="times" aria-labelledby={headingId}>
        <h3 id={headingId} className="times__heading">
          {heading}
        </h3>
        <ul className="times__list">
          {current.slots.map((slot) => {
            const label = formatTime(slot.start, timeZone);
            return (
              <li key={slot.start}>
                <button
                  type="button"
                  className="slot"
                  aria-pressed={selected?.start === slot.start}
                  aria-label={`${heading}, ${label}`}
                  onClick={() => onSelect(slot)}
                >
                  {label}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
