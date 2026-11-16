import { useMemo } from "react";

import type { Slot } from "../../api/client";
import { formatDate, formatTime } from "../../dates";
import { useLanguage } from "../../i18n";
import { groupSlotsByDay } from "./groupSlotsByDay";

interface SlotPickerProps {
  slots: readonly Slot[];
  /** IANA zone the times are displayed in. */
  timeZone: string;
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
}

export function SlotPicker({ slots, timeZone, selected, onSelect }: SlotPickerProps) {
  // Subscribes to the language, which the date helpers below read.
  useLanguage();
  const days = useMemo(() => groupSlotsByDay(slots, timeZone), [slots, timeZone]);

  return (
    <div className="days">
      {days.map(({ day, slots: daySlots }) => {
        const headingId = `day-${day}`;
        const heading = formatDate(daySlots[0]!.start, timeZone);
        return (
          <section key={day} className="day" aria-labelledby={headingId}>
            <h3 id={headingId} className="day__heading">
              {heading}
            </h3>
            <ul className="day__slots">
              {daySlots.map((slot) => {
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
        );
      })}
    </div>
  );
}
