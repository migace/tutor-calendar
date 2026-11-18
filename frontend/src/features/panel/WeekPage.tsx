import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { ApiError, changeLesson, fetchWeek, type Lesson } from "../../api/client";
import { formatDay, formatHours } from "../../dates";
import { useT, type Messages } from "../../i18n";
import { Button, ConfirmAction, Notice, PageSkeleton } from "../../ui";
import { initials } from "./PanelLayout";

function describeWeek(first: string, last: string): string {
  const sameMonth = first.slice(0, 7) === last.slice(0, 7);
  const from = formatDay(first, sameMonth ? { day: "numeric" } : { day: "numeric", month: "long" });
  return `${from} – ${formatDay(last, { day: "numeric", month: "long", year: "numeric" })}`;
}

function describeStatus(lesson: Lesson, t: Messages["week"]): string | null {
  if (lesson.status === "no_show") return t.statusNoShow;
  if (lesson.status !== "cancelled") return null;
  if (lesson.cancelled_by === "tutor") return t.statusCancelledByYou;
  return lesson.cancelled_late ? t.statusCancelledLate : t.statusCancelledByStudent;
}

export function WeekPage() {
  const all = useT();
  const t = all.week;
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

  if (isPending) return <PageSkeleton label={t.loading} />;
  if (error) {
    return (
      <Notice tone="problem" title={t.loadFailedTitle}>
        <p>{t.loadFailedBody}</p>
        <Button busy={isFetching} onClick={() => refetch()}>
          {all.common.tryAgain}
        </Button>
      </Notice>
    );
  }

  const first = week.days[0]!.date;
  const last = week.days[week.days.length - 1]!.date;
  const held = week.days.flatMap((day) => day.lessons).filter((l) => l.status !== "cancelled");
  const showsThisWeek = week.days.some((day) => day.date === week.today);
  const busyWith = change.isPending ? change.variables.id : null;

  return (
    <section aria-labelledby="week-heading" aria-busy={isFetching}>
      <title>{t.pageTitle}</title>
      <div className="week-bar">
        <div>
          <h1 className="week-bar__title" id="week-heading">
            {describeWeek(first, last)}
          </h1>
          <p className="page__meta" role="status">
            {t.lessons(held.length)} · {t.timesIn(week.timezone)}
          </p>
        </div>
        <nav className="week-bar__nav" aria-label={t.weeksNav}>
          <Link className="button button--secondary" to={`?date=${week.previous}`}>
            {t.previous}
          </Link>
          {!showsThisWeek && (
            <Link className="button button--secondary" to="/panel">
              {t.thisWeek}
            </Link>
          )}
          <Link className="button button--secondary" to={`?date=${week.next}`}>
            {t.next}
          </Link>
        </nav>
      </div>

      {change.isError && (
        <p className="form__error" role="alert">
          {change.error instanceof ApiError && change.error.detail
            ? t.refused(change.error.detail)
            : t.failed}
        </p>
      )}

      <nav className="strip" aria-label={t.overview}>
        <ol className="strip__days">
          {week.days.map((day) => {
            const count = day.lessons.filter((l) => l.status !== "cancelled").length;
            return (
              <li key={day.date}>
                <a
                  className="strip__day"
                  href={`#day-${day.date}`}
                  aria-current={day.date === week.today ? "date" : undefined}
                >
                  <span className="strip__weekday">
                    {formatDay(day.date, { weekday: "short" }).replace(/\.$/, "")}
                  </span>
                  <span className="strip__number">{formatDay(day.date, { day: "numeric" })}</span>
                  <span className="strip__count">{t.lessons(count)}</span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <ol className="week">
        {week.days.map((day) => {
          const isToday = day.date === week.today;
          const headingId = `day-${day.date}-heading`;
          return (
            <li
              key={day.date}
              className="week__day"
              id={`day-${day.date}`}
              aria-labelledby={headingId}
              aria-current={isToday ? "date" : undefined}
            >
              <h2 className="week__heading" id={headingId}>
                <span className="week__weekday">{formatDay(day.date, { weekday: "long" })}</span>{" "}
                <span className="week__date">
                  {formatDay(day.date, { day: "numeric", month: "short" })}
                </span>{" "}
                {isToday && <span className="week__today">{t.today}</span>}
              </h2>
              {day.lessons.length === 0 ? (
                <p className="week__empty">{t.noLessons}</p>
              ) : (
                <ul className="week__lessons">
                  {day.lessons.map((lesson) => {
                    const status = describeStatus(lesson, t);
                    const timeId = `lesson-${lesson.id}-time`;
                    const studentId = `lesson-${lesson.id}-student`;
                    // The server decides what is allowed; this only avoids
                    // offering a button that is certain to be refused.
                    const upcoming = new Date(lesson.start) > new Date();
                    return (
                      <li
                        key={lesson.id}
                        className={`lesson${lesson.status === "cancelled" ? " lesson--off" : ""}`}
                      >
                        <span className="lesson__time" id={timeId}>
                          {formatHours(lesson, week.timezone)}
                        </span>
                        <span className="avatar" aria-hidden="true">
                          {initials(lesson.student_name)}
                        </span>
                        <div className="lesson__who">
                          <span className="lesson__student" id={studentId}>
                            {lesson.student_name}
                          </span>
                          <a className="lesson__email" href={`mailto:${lesson.student_email}`}>
                            {lesson.student_email}
                          </a>
                        </div>
                        {(lesson.series_id || status) && (
                          <div className="lesson__notes">
                            {lesson.series_id && <span className="chip chip--accent">{t.weekly}</span>}
                            {status && (
                              <span
                                className={`chip${lesson.status === "no_show" || lesson.cancelled_late ? " chip--warning" : ""}`}
                              >
                                {status}
                              </span>
                            )}
                          </div>
                        )}
                        {lesson.status === "confirmed" && (
                          <ConfirmAction
                            label={upcoming ? t.cancel : t.noShow}
                            question={upcoming ? t.askCancel : t.askNoShow}
                            confirmLabel={upcoming ? t.yesCancel : t.yesNoShow}
                            declineLabel={t.no}
                            describedBy={`${timeId} ${studentId}`}
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
