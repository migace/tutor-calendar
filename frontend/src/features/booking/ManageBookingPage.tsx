import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  cancelManagedBooking,
  fetchManagedBooking,
  type ManagedBooking,
} from "../../api/client";
import { formatLesson, formatMoment } from "../../dates";
import { useT, type Messages } from "../../i18n";
import { Button, ConfirmAction, Notice, PageSkeleton } from "../../ui";

function tokenFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("token");
}

/** What cancelling would cost, said before the student decides. */
function terms(booking: ManagedBooking, timeZone: string, t: Messages["manage"]): string {
  if (booking.late_if_cancelled_now) return t.termsLate;
  if (booking.free_cancellation_until) {
    return t.termsUntil(formatMoment(booking.free_cancellation_until, timeZone));
  }
  return t.termsAlways;
}

/**
 * Where the link from a booking confirmation leads. Whoever has the link can
 * see the lesson and cancel it; there is no account to sign in to.
 */
export function ManageBookingPage() {
  const all = useT();
  const t = all.manage;
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
      <main className="page" id="content">
        <Notice tone="problem" level={1} title={t.badLinkTitle}>
          <p>{t.badLinkBody}</p>
        </Notice>
      </main>
    );
  }
  if (isPending) {
    return (
      <main className="page" id="content">
        <PageSkeleton label={t.loading} />
      </main>
    );
  }
  if (error) {
    return (
      <main className="page" id="content">
        <Notice tone="problem" level={1} title={t.loadFailedTitle}>
          <p>{t.loadFailedBody}</p>
          <Button busy={isFetching} onClick={() => refetch()}>
            {all.common.tryAgain}
          </Button>
        </Notice>
      </main>
    );
  }

  const when = formatLesson(booking, timeZone);
  return (
    <main className="page" id="content">
      <title>{t.pageTitle(booking.tutor_name)}</title>
      <header className="page__header">
        <p className="page__eyebrow">{t.eyebrow}</p>
        <h1 className="page__title">{booking.tutor_name}</h1>
        <p className="page__meta">
          {t.lessonFor(booking.student_name)} · {all.common.timesShownIn}{" "}
          <strong>{timeZone}</strong>
        </p>
      </header>

      {booking.status === "cancelled" ? (
        <Notice tone="neutral" title={t.cancelledTitle} focusOnMount={cancel.isSuccess}>
          <p className="notice__lead">{when}</p>
          <p>
            {booking.cancelled_by === "tutor"
              ? t.cancelledByTutor
              : booking.cancelled_late
                ? t.cancelledLate
                : t.cancelledInTime}
          </p>
        </Notice>
      ) : (
        <section className="notice" aria-labelledby="lesson-heading">
          <h2 className="notice__title" id="lesson-heading">
            {booking.status === "no_show" ? t.missedTitle : t.yourLesson}
          </h2>
          <p className="notice__lead">{when}</p>
          {booking.can_cancel ? (
            <>
              <p id="cancellation-terms">{terms(booking, timeZone, t)}</p>
              <ConfirmAction
                label={t.cancel}
                question={booking.late_if_cancelled_now ? t.askCancelLate : t.askCancel}
                confirmLabel={t.yesCancel}
                declineLabel={all.common.noKeepIt}
                describedBy="cancellation-terms"
                busy={cancel.isPending}
                onConfirm={() => cancel.mutate()}
              />
            </>
          ) : (
            <p>{booking.status === "no_show" ? t.missedBody : t.startedBody}</p>
          )}
        </section>
      )}

      {cancel.isError && (
        <p className="form__error" role="alert">
          {cancel.error instanceof ApiError && cancel.error.status === 409 ? t.refused : t.failed}
        </p>
      )}
    </main>
  );
}
