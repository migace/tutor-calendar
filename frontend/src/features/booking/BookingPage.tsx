import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError, fetchSlots, type Booking, type Slot } from "../../api/client";
import { UI_LOCALE } from "../../i18n";
import { BookingConfirmation } from "./BookingConfirmation";
import { BookingForm } from "./BookingForm";
import { describeSlot } from "./describeSlot";
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
  const [stage, setStage] = useState<Stage>(START);
  const queryClient = useQueryClient();
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["slots", slug],
    queryFn: ({ signal }) => fetchSlots(slug, signal),
  });

  if (isPending) {
    return (
      <main className="page" aria-busy="true">
        <p className="visually-hidden" role="status">
          Loading available times…
        </p>
        <div className="skeleton skeleton--title" />
        <div className="skeleton skeleton--row" />
        <div className="skeleton skeleton--row" />
      </main>
    );
  }

  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <main className="page">
        <div className="notice" role="alert">
          <h1 className="notice__title">
            {notFound ? "This booking page does not exist" : "We could not load the calendar"}
          </h1>
          <p>
            {notFound
              ? "Check the link you were given, or ask your tutor for a new one."
              : "This is a problem on our side, not yours. Your tutor's times are unchanged."}
          </p>
          {!notFound && (
            <button type="button" className="button" disabled={isFetching} onClick={() => refetch()}>
              {isFetching ? "Trying again…" : "Try again"}
            </button>
          )}
        </div>
      </main>
    );
  }

  const { tutor, slots } = data;
  const describe = (slot: { start: string; end: string }) =>
    describeSlot(slot, timeZone, UI_LOCALE);
  const refreshSlots = () => queryClient.invalidateQueries({ queryKey: ["slots", slug] });

  return (
    <main className="page">
      <header className="page__header">
        <p className="page__eyebrow">Book a lesson</p>
        <h1 className="page__title">{tutor.display_name}</h1>
        <p className="page__meta">
          {tutor.lesson_minutes}-minute lesson · Times shown in <strong>{timeZone}</strong>
          {timeZone !== tutor.timezone && <> (your tutor is in {tutor.timezone})</>}
        </p>
      </header>

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
          onBookAnother={() => setStage(START)}
        />
      )}
    </main>
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
  const lostNotice = useRef<HTMLDivElement>(null);

  // Arriving here because the chosen time was refused: put focus on the explanation.
  useEffect(() => {
    if (lostSlot) lostNotice.current?.focus();
  }, [lostSlot]);

  return (
    <>
      {lostSlot && (
        <div className="notice notice--warning" role="alert" ref={lostNotice} tabIndex={-1}>
          <h2 className="notice__title">That time is no longer available</h2>
          <p>Someone booked it just before you, or it is now too soon. Please pick another.</p>
        </div>
      )}

      {slots.length === 0 ? (
        <div className="notice">
          <h2 className="notice__title">No free times in the next two weeks</h2>
          <p>New times open up every day. Check back tomorrow or contact your tutor directly.</p>
        </div>
      ) : (
        <>
          <h2 className="visually-hidden">Available times</h2>
          <SlotPicker
            slots={slots}
            timeZone={timeZone}
            locale={UI_LOCALE}
            selected={selected}
            onSelect={onSelect}
          />
        </>
      )}

      <div className="selection">
        <p className="selection__text" role="status">
          {selected ? <>Selected: {describe(selected)}</> : "Pick a time to continue."}
        </p>
        {selected && (
          <button type="button" className="button" onClick={() => onContinue(selected)}>
            Continue
          </button>
        )}
      </div>
    </>
  );
}
