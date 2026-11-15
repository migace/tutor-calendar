import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  cancelManagedBooking,
  fetchManagedBooking,
  type ManagedBooking,
} from "../../api/client";
import { formatLesson, formatMoment } from "../../dates";
import { Button, ConfirmAction, Notice, PageSkeleton } from "../../ui";

function tokenFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("token");
}

/** What cancelling would cost, said before the student decides. */
function terms(booking: ManagedBooking, timeZone: string): string {
  if (booking.late_if_cancelled_now) {
    return "The time for cancelling free of charge has passed. You can still cancel, but the lesson will be charged.";
  }
  if (booking.free_cancellation_until) {
    return `You can cancel free of charge until ${formatMoment(booking.free_cancellation_until, timeZone)}.`;
  }
  return "You can cancel free of charge at any time before the lesson.";
}

/**
 * Where the link from a booking confirmation leads. Whoever has the link can
 * see the lesson and cancel it; there is no account to sign in to.
 */
export function ManageBookingPage() {
  const queryClient = useQueryClient();
  // The token stays in the address: this page is the link, and the fragment is
  // never sent to a server.
  const [token] = useState(tokenFromFragment);
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const key = ["managed-booking", token];

  const { data: booking, error, isPending, isFetching, refetch } = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => fetchManagedBooking(token!, signal),
    enabled: token !== null,
    retry: (failures, failure) => failures < 1 && !(failure instanceof ApiError),
  });
  const cancel = useMutation({
    mutationFn: () => cancelManagedBooking(token!),
    onSuccess: (cancelled) => queryClient.setQueryData(key, cancelled),
    // Refused: most likely cancelled meanwhile or already started. Show what is true now.
    onError: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  if (token === null || (error instanceof ApiError && error.status === 401)) {
    return (
      <main className="page">
        <Notice tone="problem" level={1} title="This link does not lead to a booking">
          <p>Check that you copied the whole link from your booking confirmation.</p>
        </Notice>
      </main>
    );
  }
  if (isPending) {
    return (
      <main className="page">
        <PageSkeleton label="Loading your booking…" />
      </main>
    );
  }
  if (error) {
    return (
      <main className="page">
        <Notice tone="problem" level={1} title="We could not load your booking">
          <p>This is a problem on our side. Your booking is unchanged.</p>
          <Button busy={isFetching} onClick={() => refetch()}>
            Try again
          </Button>
        </Notice>
      </main>
    );
  }

  const when = formatLesson(booking, timeZone);
  return (
    <main className="page">
      <title>{`Your lesson with ${booking.tutor_name}`}</title>
      <header className="page__header">
        <p className="page__eyebrow">Your booking</p>
        <h1 className="page__title">{booking.tutor_name}</h1>
        <p className="page__meta">
          Lesson for {booking.student_name} · Times shown in <strong>{timeZone}</strong>
        </p>
      </header>

      {booking.status === "cancelled" ? (
        <Notice tone="neutral" title="This lesson is cancelled" focusOnMount={cancel.isSuccess}>
          <p className="notice__lead">{when}</p>
          <p>
            {booking.cancelled_by === "tutor"
              ? "Your tutor cancelled it. You will not be charged."
              : booking.cancelled_late
                ? "It was cancelled after the free-cancellation deadline, so it is still charged."
                : "It was cancelled in time and will not be charged."}
          </p>
        </Notice>
      ) : (
        <section className="notice" aria-labelledby="lesson-heading">
          <h2 className="notice__title" id="lesson-heading">
            {booking.status === "no_show" ? "This lesson was missed" : "Your lesson"}
          </h2>
          <p className="notice__lead">{when}</p>
          {booking.can_cancel ? (
            <>
              <p id="cancellation-terms">{terms(booking, timeZone)}</p>
              <ConfirmAction
                label="Cancel lesson"
                question={
                  booking.late_if_cancelled_now
                    ? "Cancel this lesson? It will still be charged."
                    : "Cancel this lesson?"
                }
                confirmLabel="Yes, cancel"
                describedBy="cancellation-terms"
                busy={cancel.isPending}
                onConfirm={() => cancel.mutate()}
              />
            </>
          ) : (
            <p>
              {booking.status === "no_show"
                ? "Your tutor recorded that nobody came."
                : "It has started, so it can no longer be cancelled here."}
            </p>
          )}
        </section>
      )}

      {cancel.isError && (
        <p className="form__error" role="alert">
          {cancel.error instanceof ApiError && cancel.error.status === 409
            ? "This lesson could not be cancelled: it has already started or been cancelled."
            : "We could not cancel the lesson. It is still booked; please try again."}
        </p>
      )}
    </main>
  );
}
