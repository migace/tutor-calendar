import { useMemo } from "react";

import type { Slot } from "../../api/client";
import { groupSlotsByDay } from "./groupSlotsByDay";

interface SlotPickerProps {
  slots: readonly Slot[];
  /** IANA zone the times are displayed in. */
  timeZone: string;
  locale?: string;
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
}

export function SlotPicker({ slots, timeZone, locale, selected, onSelect }: SlotPickerProps) {
  const days = useMemo(() => groupSlotsByDay(slots, timeZone), [slots, timeZone]);
  const dayHeading = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        timeZone,
        weekday: "long",
        day: "numeric",
        month: "long",
      }),
    [locale, timeZone],
  );
  const time = useMemo(
    () => new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit" }),
    [locale, timeZone],
  );

  return (
    <div className="days">
      {days.map(({ day, slots: daySlots }) => {
        const headingId = `day-${day}`;
        const heading = dayHeading.format(new Date(daySlots[0]!.start));
        return (
          <section key={day} className="day" aria-labelledby={headingId}>
            <h3 id={headingId} className="day__heading">
              {heading}
            </h3>
            <ul className="day__slots">
              {daySlots.map((slot) => {
                const label = time.format(new Date(slot.start));
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
        );
      })}
    </div>
  );
}
