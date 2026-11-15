import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, fetchSlots, type Booking, type Slot } from "../../api/client";
import { UI_LOCALE } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
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
      <main className="page">
        <PageSkeleton label="Loading available times…" />
      </main>
    );
  }

  if (error) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <main className="page">
        {notFound ? (
          <Notice tone="problem" level={1} title="This booking page does not exist">
            <p>Check the link you were given, or ask your tutor for a new one.</p>
          </Notice>
        ) : (
          <Notice tone="problem" level={1} title="We could not load the calendar">
            <p>This is a problem on our side, not yours. Your tutor&rsquo;s times are unchanged.</p>
            <Button busy={isFetching} onClick={() => refetch()}>
              {isFetching ? "Trying again…" : "Try again"}
            </Button>
          </Notice>
        )}
      </main>
    );
  }

  const { tutor, slots } = data;
  const describe = (slot: { start: string; end: string }) =>
    describeSlot(slot, timeZone, UI_LOCALE);
  const refreshSlots = () => queryClient.invalidateQueries({ queryKey: ["slots", slug] });

  return (
    <main className="page">
      {/* React moves this into <head>. Each page names itself in the browser tab. */}
      <title>{`Book a lesson with ${tutor.display_name}`}</title>
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
          manageToken={stage.booking.manage_token}
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
  return (
    <>
      {lostSlot && (
        // Arriving here because the chosen time was refused: focus goes to the explanation.
        <Notice tone="warning" title="That time is no longer available" focusOnMount>
          <p>Someone booked it just before you, or it is now too soon. Please pick another.</p>
        </Notice>
      )}

      {slots.length === 0 ? (
        <Notice title="No free times in the next two weeks">
          <p>New times open up every day. Check back tomorrow or contact your tutor directly.</p>
        </Notice>
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
          <Button onClick={() => onContinue(selected)}>Continue</Button>
        )}
      </div>
    </>
  );
}
