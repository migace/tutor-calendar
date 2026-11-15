import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { fetchWeek, type Lesson } from "../../api/client";
import { UI_LOCALE } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";

/** A calendar date from the API ("2026-11-16"), formatted without shifting it into another day. */
function formatDate(date: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(UI_LOCALE, { ...options, timeZone: "UTC" }).format(
    new Date(`${date}T00:00:00Z`),
  );
}

function describeWeek(first: string, last: string): string {
  const sameMonth = first.slice(0, 7) === last.slice(0, 7);
  const from = formatDate(first, sameMonth ? { day: "numeric" } : { day: "numeric", month: "long" });
  return `${from} – ${formatDate(last, { day: "numeric", month: "long", year: "numeric" })}`;
}

export function WeekPage() {
  const [params] = useSearchParams();
  const date = params.get("date");
  const { data: week, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["week", date],
    queryFn: ({ signal }) => fetchWeek(date, signal),
    // Keep the old week on screen while the next one loads, so the page does not jump.
    placeholderData: keepPreviousData,
  });

  if (isPending) return <PageSkeleton label="Loading your week…" />;
  if (error) {
    return (
      <Notice tone="problem" title="We could not load your week">
        <p>This is a problem on our side. Your lessons are unchanged.</p>
        <Button busy={isFetching} onClick={() => refetch()}>
          Try again
        </Button>
      </Notice>
    );
  }

  const time = new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone: week.timezone,
    hour: "2-digit",
    minute: "2-digit",
  });
  const hours = (lesson: Lesson) =>
    time.formatRange(new Date(lesson.start), new Date(lesson.end));
  const first = week.days[0]!.date;
  const last = week.days[week.days.length - 1]!.date;
  const total = week.days.reduce((count, day) => count + day.lessons.length, 0);
  const showsThisWeek = week.days.some((day) => day.date === week.today);

  return (
    <section aria-labelledby="week-heading" aria-busy={isFetching}>
      <title>Your week · Tutor Calendar</title>
      <div className="week-bar">
        <div>
          <h1 className="week-bar__title" id="week-heading">
            {describeWeek(first, last)}
          </h1>
          <p className="page__meta" role="status">
            {total === 0 ? "No lessons" : total === 1 ? "1 lesson" : `${total} lessons`} · Times in{" "}
            {week.timezone}
          </p>
        </div>
        <nav className="week-bar__nav" aria-label="Weeks">
          <Link className="button button--secondary" to={`?date=${week.previous}`}>
            Previous
          </Link>
          {!showsThisWeek && (
            <Link className="button button--secondary" to="/panel">
              This week
            </Link>
          )}
          <Link className="button button--secondary" to={`?date=${week.next}`}>
            Next
          </Link>
        </nav>
      </div>

      <ol className="week">
        {week.days.map((day) => {
          const isToday = day.date === week.today;
          const headingId = `day-${day.date}`;
          return (
            <li
              key={day.date}
              className="week__day"
              aria-labelledby={headingId}
              aria-current={isToday ? "date" : undefined}
            >
              <h2 className="week__heading" id={headingId}>
                {formatDate(day.date, { weekday: "long" })}{" "}
                <span className="week__date">
                  {formatDate(day.date, { day: "numeric", month: "short" })}
                </span>
                {isToday && <span className="week__today"> Today</span>}
              </h2>
              {day.lessons.length === 0 ? (
                <p className="week__empty">No lessons</p>
              ) : (
                <ul className="week__lessons">
                  {day.lessons.map((lesson) => (
                    <li key={lesson.id} className="lesson">
                      <span className="lesson__time">{hours(lesson)}</span>
                      <span className="lesson__student">{lesson.student_name}</span>
                      <a className="lesson__email" href={`mailto:${lesson.student_email}`}>
                        {lesson.student_email}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
