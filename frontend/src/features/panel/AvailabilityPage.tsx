import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ApiError, fetchAvailability, saveAvailability, type Availability } from "../../api/client";
import { weekdayName } from "../../dates";
import { useT, type Messages } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
import { useTutor } from "./PanelLayout";
import { WeekPreview } from "./WeekPreview";
import {
  problemsIn,
  toDraft,
  toRules,
  withBlockAdded,
  withBlockChanged,
  withBlockRemoved,
  type BlockProblem,
  type Draft,
} from "./weeklyHours";

const AVAILABILITY_KEY = ["availability"] as const;

function describeProblem(problem: BlockProblem, t: Messages["hours"]): string {
  return { missing: t.problemMissing, order: t.problemOrder, overlap: t.problemOverlap }[problem];
}

export function AvailabilityPage() {
  const all = useT();
  const t = all.hours;
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: AVAILABILITY_KEY,
    queryFn: ({ signal }) => fetchAvailability(signal),
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
  // Mounted only once the hours are known, so the editor can start from them
  // without an effect that copies server state into local state.
  return <HoursEditor saved={data} />;
}

function HoursEditor({ saved }: { saved: Availability }) {
  const t = useT().hours;
  const tutor = useTutor();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => toDraft(saved.rules));
  const [showProblems, setShowProblems] = useState(false);
  const save = useMutation({
    mutationFn: saveAvailability,
    onSuccess: (stored) => {
      queryClient.setQueryData(AVAILABILITY_KEY, stored);
      // The public page reads the same hours.
      void queryClient.invalidateQueries({ queryKey: ["slots", tutor.slug] });
    },
  });

  const problems = problemsIn(draft);
  const edit = (next: Draft) => {
    setDraft(next);
    // A "Saved" message about hours that have since been edited would be a lie.
    save.reset();
  };

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (problems.size > 0) {
      setShowProblems(true);
      // Focus the first block with a problem, in reading order.
      const first = draft.flat().find((block) => problems.has(block.id));
      document.getElementById(`block-${first?.id}-start`)?.focus();
      return;
    }
    setShowProblems(false);
    save.mutate(toRules(draft));
  }

  return (
    <div className="hours-page">
      <title>{t.pageTitle}</title>
      <header className="page-head">
        <h1 className="week-bar__title">{t.heading}</h1>
        <p className="page__meta">{t.intro(saved.lesson_minutes, saved.timezone)}</p>
      </header>
      <form className="hours" noValidate onSubmit={handleSubmit}>
        {draft.map((blocks, day) => {
          const weekday = weekdayName(day);
          return (
            <fieldset key={day} className="hours__day">
              <legend className="hours__weekday">{weekday}</legend>
              <div className="hours__blocks">
                {blocks.length === 0 && <p className="week__empty">{t.notTeaching}</p>}
                {blocks.map((block, index) => {
                  const found = showProblems ? problems.get(block.id) : undefined;
                  const problemId = `block-${block.id}-problem`;
                  const position = blocks.length > 1 ? index + 1 : null;
                  const shared = {
                    type: "time",
                    className: "field__input hours__time",
                    required: true,
                    "aria-invalid": found ? true : undefined,
                    "aria-describedby": found ? problemId : undefined,
                  } as const;
                  return (
                    <div key={block.id} className="hours__block">
                      <div className="hours__row">
                        <input
                          {...shared}
                          id={`block-${block.id}-start`}
                          aria-label={t.from(weekday, position)}
                          value={block.start}
                          onChange={(event) =>
                            edit(
                              withBlockChanged(draft, day, block.id, { start: event.target.value }),
                            )
                          }
                        />
                        <span aria-hidden="true">–</span>
                        <input
                          {...shared}
                          aria-label={t.to(weekday, position)}
                          value={block.end}
                          onChange={(event) =>
                            edit(
                              withBlockChanged(draft, day, block.id, { end: event.target.value }),
                            )
                          }
                        />
                        <Button
                          variant="link"
                          aria-label={t.removeBlock(weekday, block.start, block.end)}
                          onClick={() => edit(withBlockRemoved(draft, day, block.id))}
                        >
                          {t.remove}
                        </Button>
                      </div>
                      {found && (
                        <p className="field__problem" id={problemId}>
                          {describeProblem(found, t)}
                        </p>
                      )}
                    </div>
                  );
                })}
                <Button
                  variant="secondary"
                  aria-label={t.addOn(weekday)}
                  onClick={() => edit(withBlockAdded(draft, day))}
                >
                  {t.add}
                </Button>
              </div>
            </fieldset>
          );
        })}

        <div className="hours__footer">
          {save.isError && (
            <p className="form__error" role="alert">
              {save.error instanceof ApiError && save.error.status === 422
                ? t.refused(save.error.detail)
                : t.failed}
            </p>
          )}
          <p className="hours__status" role="status">
            {save.isSuccess && t.saved}
          </p>
          <Button type="submit" busy={save.isPending}>
            {save.isPending ? t.saving : t.save}
          </Button>
        </div>
      </form>
      <WeekPreview draft={draft} />
    </div>
  );
}
