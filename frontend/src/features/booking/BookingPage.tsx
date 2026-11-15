import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, fetchSlots, type Slot } from "../../api/client";
import { UI_LOCALE } from "../../i18n";
import { SlotPicker } from "./SlotPicker";

const visitorTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function BookingPage({ slug }: { slug: string }) {
  const [selected, setSelected] = useState<Slot | null>(null);
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
  const sameZone = visitorTimeZone === tutor.timezone;

  return (
    <main className="page">
      <header className="page__header">
        <p className="page__eyebrow">Book a lesson</p>
        <h1 className="page__title">{tutor.display_name}</h1>
        <p className="page__meta">
          {tutor.lesson_minutes}-minute lesson · Times shown in <strong>{visitorTimeZone}</strong>
          {!sameZone && <> (your tutor is in {tutor.timezone})</>}
        </p>
      </header>

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
            timeZone={visitorTimeZone}
            locale={UI_LOCALE}
            selected={selected}
            onSelect={setSelected}
          />
        </>
      )}

      <p className="selection" role="status">
        {selected ? <>Selected: {describe(selected)}</> : "Pick a time to continue."}
      </p>
    </main>
  );
}

function describe(slot: Slot): string {
  const day = new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone: visitorTimeZone,
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(slot.start));
  const time = new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone: visitorTimeZone,
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${day}, ${time.formatRange(new Date(slot.start), new Date(slot.end))}`;
}
