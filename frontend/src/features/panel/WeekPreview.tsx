import { formatDay, formatMinutes } from "../../dates";
import { useT } from "../../i18n";
import type { Draft } from "./weeklyHours";

const minutesOf = (time: string) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));

/**
 * The hours being edited, drawn as a week. A picture of the form next to it,
 * so it is hidden from screen readers; the total underneath is not.
 */
export function WeekPreview({ draft }: { draft: Draft }) {
  const t = useT().hours;
  const blocks = draft.map((day) =>
    day
      .filter((block) => block.start && block.end && block.end > block.start)
      .map((block) => ({ id: block.id, from: minutesOf(block.start), to: minutesOf(block.end) })),
  );
  const all = blocks.flat();
  // Whole hours around what is open, and never less than 8:00–20:00.
  const first = Math.min(8 * 60, ...all.map((block) => Math.floor(block.from / 60) * 60));
  const last = Math.max(20 * 60, ...all.map((block) => Math.ceil(block.to / 60) * 60));
  const span = last - first;
  const total = all.reduce((sum, block) => sum + block.to - block.from, 0);
  const hours = Array.from({ length: span / 60 + 1 }, (_, i) => first / 60 + i).filter(
    (hour) => hour % 2 === 0,
  );

  return (
    <aside className="preview" aria-labelledby="preview-heading">
      <h2 className="preview__heading" id="preview-heading">
        {t.previewHeading}
      </h2>
      <div className="preview__chart" aria-hidden="true">
        <div className="preview__hours">
          {hours.map((hour) => (
            <span key={hour} style={{ top: `${((hour * 60 - first) / span) * 100}%` }}>
              {hour}
            </span>
          ))}
        </div>
        {blocks.map((day, index) => (
          <div key={index} className="preview__day">
            <span className="preview__weekday">{formatDay(`2024-01-0${index + 1}`, { weekday: "narrow" })}</span>
            <div className="preview__column">
              {day.map((block) => (
                <span
                  key={block.id}
                  className="preview__block"
                  style={{
                    top: `${((block.from - first) / span) * 100}%`,
                    height: `${((block.to - block.from) / span) * 100}%`,
                  }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="preview__total">{t.previewTotal(formatMinutes(total))}</p>
    </aside>
  );
}
