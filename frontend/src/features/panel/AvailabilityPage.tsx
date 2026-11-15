import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ApiError, fetchAvailability, saveAvailability, type Availability } from "../../api/client";
import { Button, Notice, PageSkeleton } from "../../ui";
import { useTutor } from "./PanelLayout";
import {
  WEEKDAYS,
  problemsIn,
  toDraft,
  toRules,
  withBlockAdded,
  withBlockChanged,
  withBlockRemoved,
  type Draft,
} from "./weeklyHours";

const AVAILABILITY_KEY = ["availability"] as const;

export function AvailabilityPage() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: AVAILABILITY_KEY,
    queryFn: ({ signal }) => fetchAvailability(signal),
  });

  if (isPending) return <PageSkeleton label="Loading your hours…" />;
  if (error) {
    return (
      <Notice tone="problem" title="We could not load your hours">
        <p>This is a problem on our side. Nothing has been changed.</p>
        <Button busy={isFetching} onClick={() => refetch()}>
          Try again
        </Button>
      </Notice>
    );
  }
  // Mounted only once the hours are known, so the editor can start from them
  // without an effect that copies server state into local state.
  return <HoursEditor saved={data} />;
}

function HoursEditor({ saved }: { saved: Availability }) {
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
    <form className="hours" noValidate onSubmit={handleSubmit}>
      <title>Weekly hours · Tutor Calendar</title>
      <header>
        <h1 className="week-bar__title">Weekly hours</h1>
        <p className="page__meta">
          When visitors can book a {saved.lesson_minutes}-minute lesson. Times are in{" "}
          {saved.timezone}. Lessons that are already booked are not affected.
        </p>
      </header>

      {WEEKDAYS.map((weekday, day) => {
        const blocks = draft[day]!;
        return (
          <fieldset key={weekday} className="hours__day">
            <legend className="hours__weekday">{weekday}</legend>
            {blocks.length === 0 && <p className="week__empty">Not teaching</p>}
            {blocks.map((block, index) => {
              const problem = showProblems ? problems.get(block.id) : undefined;
              const problemId = `block-${block.id}-problem`;
              const position = blocks.length > 1 ? `, hours ${index + 1}` : "";
              const shared = {
                type: "time",
                className: "field__input hours__time",
                required: true,
                "aria-invalid": problem ? true : undefined,
                "aria-describedby": problem ? problemId : undefined,
              } as const;
              return (
                <div key={block.id} className="hours__block">
                  <div className="hours__row">
                    <input
                      {...shared}
                      id={`block-${block.id}-start`}
                      aria-label={`${weekday}${position}, from`}
                      value={block.start}
                      onChange={(event) =>
                        edit(withBlockChanged(draft, day, block.id, { start: event.target.value }))
                      }
                    />
                    <span aria-hidden="true">–</span>
                    <input
                      {...shared}
                      aria-label={`${weekday}${position}, to`}
                      value={block.end}
                      onChange={(event) =>
                        edit(withBlockChanged(draft, day, block.id, { end: event.target.value }))
                      }
                    />
                    <Button
                      variant="link"
                      aria-label={`Remove ${weekday} ${block.start}–${block.end}`}
                      onClick={() => edit(withBlockRemoved(draft, day, block.id))}
                    >
                      Remove
                    </Button>
                  </div>
                  {problem && (
                    <p className="field__problem" id={problemId}>
                      {problem}
                    </p>
                  )}
                </div>
              );
            })}
            <Button
              variant="secondary"
              aria-label={`Add hours on ${weekday}`}
              onClick={() => edit(withBlockAdded(draft, day))}
            >
              Add hours
            </Button>
          </fieldset>
        );
      })}

      <div className="hours__footer">
        {save.isError && (
          <p className="form__error" role="alert">
            {save.error instanceof ApiError && save.error.status === 422
              ? `The server did not accept these hours${save.error.detail ? `: ${save.error.detail}` : ""}.`
              : "We could not save your hours. Nothing has been changed; please try again."}
          </p>
        )}
        <p className="hours__status" role="status">
          {save.isSuccess && "Saved. Visitors now see these hours."}
        </p>
        <Button type="submit" busy={save.isPending}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
