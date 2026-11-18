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
import { useT, type Messages } from "../../i18n";
import { Button, ConfirmAction, Notice, PageSkeleton, TextField } from "../../ui";
import { useTutor } from "./PanelLayout";

const SERIES_KEY = ["series"] as const;
const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

type Field = "student_name" | "student_email" | "first_day" | "start" | "weeks";
type Form = Record<Field, string>;
const EMPTY: Form = { student_name: "", student_email: "", first_day: "", start: "", weeks: "10" };

function check(form: Form, t: Messages["series"]): Partial<Record<Field, string>> {
  const problems: Partial<Record<Field, string>> = {};
  const weeks = Number(form.weeks);
  if (!form.student_name.trim()) problems.student_name = t.nameMissing;
  if (!LOOKS_LIKE_EMAIL.test(form.student_email.trim())) problems.student_email = t.emailInvalid;
  if (!form.first_day) problems.first_day = t.firstDayMissing;
  if (!form.start) problems.start = t.timeMissing;
  if (!Number.isInteger(weeks) || weeks < 1 || weeks > 52) problems.weeks = t.weeksInvalid;
  return problems;
}

function describePlan(series: Series, t: Messages["series"]): string {
  return t.plan(formatDay(series.first_day, { weekday: "long" }), series.start.slice(0, 5));
}

function listDays(days: readonly string[]): string {
  return days.map((day) => formatDay(day, { day: "numeric", month: "long" })).join(", ");
}

export function SeriesPage() {
  const all = useT();
  const t = all.series;
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
      <title>{t.pageTitle}</title>
      <header className="page-head">
        <h1 className="week-bar__title">{t.heading}</h1>
        <p className="page__meta">{t.intro(tutor.timezone)}</p>
      </header>

      <NewSeries onCreated={refresh} />

      <section aria-labelledby="series-heading">
        <h2 className="step__heading" id="series-heading">
          {t.yours}
        </h2>
        {end.isError && (
          <p className="form__error" role="alert">
            {t.endFailed}
          </p>
        )}
        {isPending ? (
          <PageSkeleton label={t.loading} />
        ) : error ? (
          <Notice tone="problem" title={t.loadFailedTitle}>
            <Button busy={isFetching} onClick={() => refetch()}>
              {all.common.tryAgain}
            </Button>
          </Notice>
        ) : data.length === 0 ? (
          <p className="week__empty">{t.none}</p>
        ) : (
          <ul className="regulars__list">
            {data.map((series) => {
              const now = new Date();
              const upcoming = series.lessons.filter(
                (lesson) => lesson.status === "confirmed" && new Date(lesson.start) > now,
              );
              const titleId = `series-${series.id}`;
              const next =
                upcoming[0] &&
                formatDay(upcoming[0].start.slice(0, 10), { day: "numeric", month: "long" });
              return (
                <li key={series.id} className="day">
                  <h3 className="day__heading" id={titleId}>
                    {series.student_name} · {describePlan(series, t)}
                  </h3>
                  <p className="page__meta">
                    {next ? t.left(upcoming.length, next) : t.noneLeft}
                    {series.days_without_lesson.length > 0 &&
                      ` ${t.noLessonOn(listDays(series.days_without_lesson))}`}
                  </p>
                  {upcoming.length > 0 && (
                    <ConfirmAction
                      label={t.end}
                      question={t.askEnd(upcoming.length)}
                      confirmLabel={t.yesEnd}
                      declineLabel={all.common.noKeepIt}
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
  const t = useT().series;
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
    const found = check(form, t);
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
    <section className="card" aria-labelledby="new-series-heading">
      <h2 className="step__heading" id="new-series-heading">
        {t.addHeading}
      </h2>
      <form className="form regulars__form" noValidate ref={formElement} onSubmit={handleSubmit}>
        <TextField {...bind("student_name")} label={t.studentName} autoComplete="off" />
        <TextField
          {...bind("student_email")}
          label={t.studentEmail}
          type="email"
          autoComplete="off"
        />
        <TextField
          {...bind("first_day")}
          label={t.firstLesson}
          hint={t.firstLessonHint}
          type="date"
        />
        <TextField {...bind("start")} label={t.time} type="time" />
        <TextField
          {...bind("weeks")}
          label={t.weeks}
          hint={t.weeksHint}
          type="number"
          inputMode="numeric"
          min={1}
          max={52}
        />

        {conflicts && (
          <Notice tone="warning" title={t.clashTitle}>
            <p>{t.clashBody(listDays(conflicts))}</p>
            <Button busy={create.isPending} onClick={() => create.mutate(plan(true))}>
              {t.bookOthers}
            </Button>
          </Notice>
        )}
        {create.isError && !conflicts && (
          <p className="form__error" role="alert">
            {create.error instanceof ApiError && create.error.status === 422
              ? t.refused(create.error.detail)
              : t.failed}
          </p>
        )}
        <p className="hours__status" role="status">
          {create.isSuccess && t.booked(create.data.lessons.length, create.data.student_name)}
        </p>
        <Button type="submit" busy={create.isPending}>
          {create.isPending ? t.submitting : t.submit}
        </Button>
      </form>
    </section>
  );
}
