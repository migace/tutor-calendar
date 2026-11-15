import { useMutation } from "@tanstack/react-query";
import { useRef } from "react";

import { ApiError, createBooking, type Booking, type Slot } from "../../api/client";

export interface StudentDetails {
  name: string;
  email: string;
}

/** A definite answer from the server. Asking again would not change it. */
function isFinal(error: unknown): boolean {
  return error instanceof ApiError && error.status < 500;
}

/**
 * Books `slot` for a student.
 *
 * Every distinct request gets one idempotency key, and every repeat of that
 * request reuses it. That is what makes it safe to retry here automatically
 * when the network drops or the server stumbles: if the first attempt did reach
 * the database, the retry is answered with that same booking, not a second one.
 */
export function useBookLesson(slug: string, slot: Slot) {
  const lastAttempt = useRef<{ request: string; key: string } | null>(null);

  return useMutation<Booking, Error, StudentDetails>({
    mutationFn: ({ name, email }) => {
      const request = JSON.stringify([slug, slot.start, name, email]);
      if (lastAttempt.current?.request !== request) {
        lastAttempt.current = { request, key: crypto.randomUUID() };
      }
      return createBooking(
        slug,
        { start: slot.start, student_name: name, student_email: email },
        lastAttempt.current.key,
      );
    },
    retry: (failures, error) => failures < 2 && !isFinal(error),
  });
}
