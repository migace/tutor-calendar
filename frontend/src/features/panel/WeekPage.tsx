import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { ApiError, changeLesson, fetchWeek, type Lesson } from "../../api/client";
import { formatDay } from "../../dates";
import { UI_LOCALE } from "../../i18n";
import { Button, ConfirmAction, Notice, PageSkeleton } from "../../ui";

function describeWeek(first: string, last: string): string {
  const sameMonth = first.slice(0, 7) === last.slice(0, 7);
  const from = formatDay(first, sameMonth ? { day: "numeric" } : { day: "numeric", month: "long" });
  return `${from} – ${formatDay(last, { day: "numeric", month: "long", year: "numeric" })}`;
}

function describeStatus(lesson: Lesson): string | null {
  if (lesson.status === "no_show") return "No-show";
  if (lesson.status !== "cancelled") return null;
  if (lesson.cancelled_by === "tutor") return "Cancelled by you";
  return lesson.cancelled_late ? "Cancelled late by the student" : "Cancelled by the student";
}

export function WeekPage() {
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const date = params.get("date");
  const { data: week, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["week", date],
    queryFn: ({ signal }) => fetchWeek(date, signal),
    // Keep the old week on screen while the next one loads, so the page does not jump.
    placeholderData: keepPreviousData,
  });
  const change = useMutation({
    mutationFn: ({ id, to }: { id: string; to: "cancellation" | "no-show" }) =>
      changeLesson(id, to),
    // Whether it worked or was refused, what is on screen may be out of date.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["week"] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
    },
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
  const hours = (lesson: Lesson) => time.formatRange(new Date(lesson.start), new Date(lesson.end));
  const first = week.days[0]!.date;
  const last = week.days[week.days.length - 1]!.date;
  const held = week.days.flatMap((day) => day.lessons).filter((l) => l.status !== "cancelled");
  const showsThisWeek = week.days.some((day) => day.date === week.today);
  const busyWith = change.isPending ? change.variables.id : null;

  return (
    <section aria-labelledby="week-heading" aria-busy={isFetching}>
      <title>Your week · Tutor Calendar</title>
      <div className="week-bar">
        <div>
          <h1 className="week-bar__title" id="week-heading">
            {describeWeek(first, last)}
          </h1>
          <p className="page__meta" role="status">
            {held.length === 0
              ? "No lessons"
              : held.length === 1
                ? "1 lesson"
                : `${held.length} lessons`}{" "}
            · Times in {week.timezone}
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

      {change.isError && (
        <p className="form__error" role="alert">
          {change.error instanceof ApiError && change.error.detail
            ? `That was not possible: ${change.error.detail}.`
            : "We could not change the lesson. Nothing was changed; please try again."}
        </p>
      )}

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
                {formatDay(day.date, { weekday: "long" })}{" "}
                <span className="week__date">
                  {formatDay(day.date, { day: "numeric", month: "short" })}
                </span>
                {isToday && <span className="week__today"> Today</span>}
              </h2>
              {day.lessons.length === 0 ? (
                <p className="week__empty">No lessons</p>
              ) : (
                <ul className="week__lessons">
                  {day.lessons.map((lesson) => {
                    const status = describeStatus(lesson);
                    const labelId = `lesson-${lesson.id}`;
                    // The server decides what is allowed; this only avoids
                    // offering a button that is certain to be refused.
                    const upcoming = new Date(lesson.start) > new Date();
                    return (
                      <li
                        key={lesson.id}
                        className={`lesson${lesson.status === "cancelled" ? " lesson--off" : ""}`}
                      >
                        <span id={labelId}>
                          <span className="lesson__time">{hours(lesson)}</span>{" "}
                          <span className="lesson__student">{lesson.student_name}</span>
                        </span>
                        <a className="lesson__email" href={`mailto:${lesson.student_email}`}>
                          {lesson.student_email}
                        </a>
                        {lesson.series_id && <span className="lesson__tag">Weekly</span>}
                        {status && <span className="lesson__status">{status}</span>}
                        {lesson.status === "confirmed" && (
                          <ConfirmAction
                            label={upcoming ? "Cancel" : "No-show"}
                            question={
                              upcoming
                                ? "Cancel this lesson? The student is not charged."
                                : "Record that the student did not come? The lesson is charged."
                            }
                            confirmLabel={upcoming ? "Yes, cancel" : "Yes, no-show"}
                            declineLabel="No"
                            describedBy={labelId}
                            busy={busyWith === lesson.id}
                            onConfirm={() =>
                              change.mutate({
                                id: lesson.id,
                                to: upcoming ? "cancellation" : "no-show",
                              })
                            }
                          />
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
