import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, fetchSlots, type Booking, type Slot } from "../../api/client";
import { formatLesson } from "../../dates";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
import { CheckIcon } from "../frame/icons";
import { BookingConfirmation } from "./BookingConfirmation";
import { BookingForm } from "./BookingForm";
import { SlotPicker } from "./SlotPicker";

/**
 * Where the visitor is in the booking flow. One value instead of several
 * flags, so that states such as "confirmed but no booking" cannot exist.
 */
type Stage =
  | { step: "pick"; selected: Slot | null; lostSlot: boolean }
  | { step: "details"; slot: Slot }
  | { step: "done"; booking: Booking };

const START: Stage = { step: "pick", selected: null, lostSlot: false };

interface BookingPageProps {
  slug: string;
  /** IANA zone to show times in. Defaults to the visitor's own. */
  timeZone?: string;
}

export function BookingPage({
  slug,
  timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone,
}: BookingPageProps) {
  const t = useT();
  const [stage, setStage] = useState<Stage>(START);
  const queryClient = useQueryClient();
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["slots", slug],
    queryFn: ({ signal }) => fetchSlots(slug, signal),
  });

  if (isPending) {
    return (
      <main className="page" id="content">
        <PageSkeleton label={t.booking.loading} />
      </main>
    );
  }

  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <main className="page" id="content">
        {notFound ? (
          <Notice tone="problem" level={1} title={t.booking.notFoundTitle}>
            <p>{t.booking.notFoundBody}</p>
          </Notice>
        ) : (
          <Notice tone="problem" level={1} title={t.booking.loadFailedTitle}>
            <p>{t.booking.loadFailedBody}</p>
            <Button busy={isFetching} onClick={() => refetch()}>
              {isFetching ? t.common.tryingAgain : t.common.tryAgain}
            </Button>
          </Notice>
        )}
      </main>
    );
  }

  const { tutor, slots } = data;
  const describe = (slot: { start: string; end: string }) => formatLesson(slot, timeZone);
  const refreshSlots = () => queryClient.invalidateQueries({ queryKey: ["slots", slug] });

  const step = { pick: 1, details: 2, done: 3 }[stage.step];

  return (
    <main className="page page--booking" id="content">
      {/* React moves this into <head>. Each page names itself in the browser tab. */}
      <title>{t.booking.pageTitle(tutor.display_name)}</title>
      <div className="booking">
        <header className="booking__intro">
          <p className="page__eyebrow">{t.booking.eyebrow}</p>
          <h1 className="page__title">{tutor.display_name}</h1>
          <p className="page__meta">
            {t.booking.lessonLength(tutor.lesson_minutes)} · {t.common.timesShownIn}{" "}
            <strong>{timeZone}</strong>
            {timeZone !== tutor.timezone && <> {t.booking.tutorIsIn(tutor.timezone)}</>}
          </p>
          <Steps current={step} />
        </header>

        <div className="booking__card">
          {stage.step === "pick" && (
            <PickTime
              slots={slots}
              // A time that vanished from a refreshed list is no longer selected.
              selected={slots.find((slot) => slot.start === stage.selected?.start) ?? null}
              lostSlot={stage.lostSlot}
              timeZone={timeZone}
              describe={describe}
              onSelect={(slot) => setStage({ step: "pick", selected: slot, lostSlot: false })}
              onContinue={(slot) => setStage({ step: "details", slot })}
            />
          )}

          {stage.step === "details" && (
            <BookingForm
              slug={slug}
              slot={stage.slot}
              slotLabel={describe(stage.slot)}
              onChangeTime={() => setStage({ step: "pick", selected: stage.slot, lostSlot: false })}
              onSlotUnavailable={() => {
                setStage({ step: "pick", selected: null, lostSlot: true });
                void refreshSlots();
              }}
              onBooked={(booking) => {
                setStage({ step: "done", booking });
                void refreshSlots();
              }}
            />
          )}

          {stage.step === "done" && (
            <BookingConfirmation
              slotLabel={describe(stage.booking)}
              tutorName={tutor.display_name}
              lessonMinutes={tutor.lesson_minutes}
              manageToken={stage.booking.manage_token}
              onBookAnother={() => setStage(START)}
            />
          )}
        </div>
      </div>
    </main>
  );
}

/** Where the visitor is: pick a time, give details, done. */
function Steps({ current }: { current: number }) {
  const t = useT().booking;
  const names = [t.stepTime, t.stepDetails, t.stepDone];
  return (
    <ol className="steps" aria-label={t.steps}>
      {names.map((name, index) => {
        const step = index + 1;
        const state = step < current ? "done" : step === current ? "current" : "next";
        return (
          <li
            key={name}
            className={`steps__item steps__item--${state}`}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className="steps__number" aria-hidden="true">
              {state === "done" ? <CheckIcon /> : step}
            </span>
            <span className="steps__name">
              <span className="visually-hidden">{t.stepOf(step, names.length)}: </span>
              {name}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

interface PickTimeProps {
  slots: readonly Slot[];
  selected: Slot | null;
  lostSlot: boolean;
  timeZone: string;
  describe: (slot: Slot) => string;
  onSelect: (slot: Slot) => void;
  onContinue: (slot: Slot) => void;
}

function PickTime({
  slots,
  selected,
  lostSlot,
  timeZone,
  describe,
  onSelect,
  onContinue,
}: PickTimeProps) {
  const t = useT();
  return (
    <>
      {lostSlot && (
        // Arriving here because the chosen time was refused: focus goes to the explanation.
        <Notice tone="warning" title={t.booking.lostTitle} focusOnMount>
          <p>{t.booking.lostBody}</p>
        </Notice>
      )}

      {slots.length === 0 ? (
        <Notice title={t.booking.emptyTitle}>
          <p>{t.booking.emptyBody}</p>
        </Notice>
      ) : (
        <>
          <h2 className="visually-hidden">{t.booking.availableTimes}</h2>
          <SlotPicker slots={slots} timeZone={timeZone} selected={selected} onSelect={onSelect} />
        </>
      )}

      <div className="selection">
        <p className="selection__text" role="status">
          {selected ? t.booking.selected(describe(selected)) : t.booking.pickATime}
        </p>
        {selected && <Button onClick={() => onContinue(selected)}>{t.booking.continue}</Button>}
      </div>
    </>
  );
}
