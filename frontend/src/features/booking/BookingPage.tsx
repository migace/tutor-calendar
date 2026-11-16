import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, fetchSlots, type Booking, type Slot } from "../../api/client";
import { formatLesson } from "../../dates";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
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

  return (
    <main className="page" id="content">
      {/* React moves this into <head>. Each page names itself in the browser tab. */}
      <title>{t.booking.pageTitle(tutor.display_name)}</title>
      <header className="page__header">
        <p className="page__eyebrow">{t.booking.eyebrow}</p>
        <h1 className="page__title">{tutor.display_name}</h1>
        <p className="page__meta">
          {t.booking.lessonLength(tutor.lesson_minutes)} · {t.common.timesShownIn}{" "}
          <strong>{timeZone}</strong>
          {timeZone !== tutor.timezone && <> {t.booking.tutorIsIn(tutor.timezone)}</>}
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
