import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  conflictsIn,
  endSeries,
  fetchSeries,
  startSeries,
  type Series,
  type SeriesPlan,
} from "../../api/client";
import { formatDay } from "../../dates";
import { Button, ConfirmAction, Notice, PageSkeleton, TextField } from "../../ui";
import { useTutor } from "./PanelLayout";

const SERIES_KEY = ["series"] as const;
const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

type Field = "student_name" | "student_email" | "first_day" | "start" | "weeks";
type Form = Record<Field, string>;
const EMPTY: Form = { student_name: "", student_email: "", first_day: "", start: "", weeks: "10" };

function check(form: Form): Partial<Record<Field, string>> {
  const problems: Partial<Record<Field, string>> = {};
  const weeks = Number(form.weeks);
  if (!form.student_name.trim()) problems.student_name = "Enter the student's name.";
  if (!LOOKS_LIKE_EMAIL.test(form.student_email.trim())) {
    problems.student_email = "Enter an email address like name@example.com.";
  }
  if (!form.first_day) problems.first_day = "Choose the day of the first lesson.";
  if (!form.start) problems.start = "Choose a time.";
  if (!Number.isInteger(weeks) || weeks < 1 || weeks > 52) {
    problems.weeks = "Enter a number of weeks from 1 to 52.";
  }
  return problems;
}

function describePlan(series: Series): string {
  const weekday = formatDay(series.first_day, { weekday: "long" });
  return `${weekday}s at ${series.start.slice(0, 5)}`;
}

function listDays(days: readonly string[]): string {
  return days.map((day) => formatDay(day, { day: "numeric", month: "long" })).join(", ");
}

export function SeriesPage() {
  const tutor = useTutor();
  const queryClient = useQueryClient();
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: SERIES_KEY,
    queryFn: ({ signal }) => fetchSeries(signal),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: SERIES_KEY });
    void queryClient.invalidateQueries({ queryKey: ["week"] });
    void queryClient.invalidateQueries({ queryKey: ["slots", tutor.slug] });
  };
  const end = useMutation({ mutationFn: endSeries, onSettled: refresh });

  return (
    <div className="regulars">
      <title>Regular lessons · Tutor Calendar</title>
      <header>
        <h1 className="week-bar__title">Regular lessons</h1>
        <p className="page__meta">
          A lesson at the same time every week for one student. Times are in {tutor.timezone}.
        </p>
      </header>

      <NewSeries onCreated={refresh} />

      <section aria-labelledby="series-heading">
        <h2 className="step__heading" id="series-heading">
          Your weekly lessons
        </h2>
        {end.isError && (
          <p className="form__error" role="alert">
            We could not end the series. Nothing was changed; please try again.
          </p>
        )}
        {isPending ? (
          <PageSkeleton label="Loading your weekly lessons…" />
        ) : error ? (
          <Notice tone="problem" title="We could not load your weekly lessons">
            <Button busy={isFetching} onClick={() => refetch()}>
              Try again
            </Button>
          </Notice>
        ) : data.length === 0 ? (
          <p className="week__empty">None yet.</p>
        ) : (
          <ul className="regulars__list">
            {data.map((series) => {
              const now = new Date();
              const upcoming = series.lessons.filter(
                (lesson) => lesson.status === "confirmed" && new Date(lesson.start) > now,
              );
              const titleId = `series-${series.id}`;
              return (
                <li key={series.id} className="day">
                  <h3 className="day__heading" id={titleId}>
                    {series.student_name} · {describePlan(series)}
                  </h3>
                  <p className="page__meta">
                    {upcoming.length === 0
                      ? "No lessons left."
                      : `${upcoming.length} still to come, next on ${formatDay(
                          upcoming[0]!.start.slice(0, 10),
                          { day: "numeric", month: "long" },
                        )}.`}
                    {series.days_without_lesson.length > 0 &&
                      ` No lesson on ${listDays(series.days_without_lesson)}.`}
                  </p>
                  {upcoming.length > 0 && (
                    <ConfirmAction
                      label="End series"
                      question={`Cancel the ${upcoming.length} lessons still to come? The student is not charged.`}
                      confirmLabel="Yes, end it"
                      describedBy={titleId}
                      busy={end.isPending && end.variables === series.id}
                      onConfirm={() => end.mutate(series.id)}
                    />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function NewSeries({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState<Form>(EMPTY);
  const [problems, setProblems] = useState<Partial<Record<Field, string>>>({});
  const formElement = useRef<HTMLFormElement>(null);
  // One id per distinct plan, reused when the same plan is sent again, so a
  // repeat after a lost response returns the first series and books nothing twice.
  const attempt = useRef<{ plan: string; id: string } | null>(null);

  const create = useMutation({
    mutationFn: (plan: SeriesPlan) => {
      // Skipping conflicts is a second attempt at the same series, not another one.
      const fingerprint = JSON.stringify([
        plan.student_name,
        plan.student_email,
        plan.first_day,
        plan.start,
        plan.weeks,
      ]);
      if (attempt.current?.plan !== fingerprint) {
        attempt.current = { plan: fingerprint, id: crypto.randomUUID() };
      }
      return startSeries(attempt.current.id, plan);
    },
    onSuccess: () => {
      setForm(EMPTY);
      onCreated();
    },
  });
  const conflicts = conflictsIn(create.error);

  function plan(skipConflicts: boolean): SeriesPlan {
    return {
      student_name: form.student_name.trim(),
      student_email: form.student_email.trim(),
      first_day: form.first_day,
      start: form.start,
      weeks: Number(form.weeks),
      skip_conflicts: skipConflicts,
    };
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const found = check(form);
    setProblems(found);
    const first = (Object.keys(EMPTY) as Field[]).find((field) => found[field]);
    if (first) {
      formElement.current?.querySelector<HTMLInputElement>(`[name="${first}"]`)?.focus();
      return;
    }
    create.mutate(plan(false));
  }

  const bind = (field: Field) => ({
    name: field,
    value: form[field],
    error: problems[field],
    required: true,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
      setForm({ ...form, [field]: event.target.value });
      // Messages about the plan as it was no longer apply.
      create.reset();
    },
  });

  return (
    <section aria-labelledby="new-series-heading">
      <h2 className="step__heading" id="new-series-heading">
        Add a weekly lesson
      </h2>
      <form className="form regulars__form" noValidate ref={formElement} onSubmit={handleSubmit}>
        <TextField {...bind("student_name")} label="Student's name" autoComplete="off" />
        <TextField {...bind("student_email")} label="Student's email" type="email" autoComplete="off" />
        <TextField
          {...bind("first_day")}
          label="First lesson"
          hint="Later lessons are on the same weekday."
          type="date"
        />
        <TextField {...bind("start")} label="Time" type="time" />
        <TextField
          {...bind("weeks")}
          label="Number of weeks"
          hint="From 1 to 52."
          type="number"
          inputMode="numeric"
          min={1}
          max={52}
        />

        {conflicts && (
          <Notice tone="warning" title="Some of these lessons clash with others">
            <p>
              There is already a lesson on {listDays(conflicts)}. Nothing has been booked yet.
            </p>
            <Button busy={create.isPending} onClick={() => create.mutate(plan(true))}>
              Book the other weeks
            </Button>
          </Notice>
        )}
        {create.isError && !conflicts && (
          <p className="form__error" role="alert">
            {create.error instanceof ApiError && create.error.status === 422
              ? `These lessons cannot be booked${create.error.detail ? `: ${create.error.detail}` : ""}.`
              : "We could not book these lessons. Nothing was booked; it is safe to try again."}
          </p>
        )}
        <p className="hours__status" role="status">
          {create.isSuccess &&
            `Booked ${create.data.lessons.length} lessons for ${create.data.student_name}.`}
        </p>
        <Button type="submit" busy={create.isPending}>
          {create.isPending ? "Booking…" : "Book these lessons"}
        </Button>
      </form>
    </section>
  );
}
