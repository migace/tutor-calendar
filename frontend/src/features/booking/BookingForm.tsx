import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { ApiError, type Booking, type Slot } from "../../api/client";
import { useT, type Messages } from "../../i18n";
import { Button, TextField } from "../../ui";
import { useBookLesson, type StudentDetails } from "./useBookLesson";

interface BookingFormProps {
  slug: string;
  slot: Slot;
  /** The chosen time, already formatted for the visitor. */
  slotLabel: string;
  onBooked: (booking: Booking) => void;
  /** The server refused the time: someone else took it, or it is now too soon. */
  onSlotUnavailable: () => void;
  onChangeTime: () => void;
}

type Field = keyof StudentDetails;
type Problems = Partial<Record<Field, string>>;

const MAX_NAME_LENGTH = 120;
// Deliberately loose: something, an @, something with a dot. The server has the final say.
const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

function check({ name, email }: StudentDetails, t: Messages["booking"]): Problems {
  const problems: Problems = {};
  if (!name) {
    problems.name = t.nameMissing;
  } else if (name.length > MAX_NAME_LENGTH) {
    problems.name = t.nameTooLong(MAX_NAME_LENGTH);
  }
  if (!email) {
    problems.email = t.emailMissing;
  } else if (!LOOKS_LIKE_EMAIL.test(email)) {
    problems.email = t.emailInvalid;
  }
  return problems;
}

function isRefusal(error: Error | null): boolean {
  return error instanceof ApiError && error.status === 409;
}

export function BookingForm({
  slug,
  slot,
  slotLabel,
  onBooked,
  onSlotUnavailable,
  onChangeTime,
}: BookingFormProps) {
  const t = useT().booking;
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const emailInput = useRef<HTMLInputElement>(null);
  const [details, setDetails] = useState<StudentDetails>({ name: "", email: "" });
  const [problems, setProblems] = useState<Problems>({});
  const booking = useBookLesson(slug, slot);

  // This step replaces the list of times, so tell keyboard and screen reader
  // users where they are now.
  useEffect(() => heading.current?.focus(), []);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const tidied = { name: details.name.trim(), email: details.email.trim() };
    const found = check(tidied, t);
    setProblems(found);

    const firstInvalid = (["name", "email"] as const).find((field) => found[field]);
    if (firstInvalid) {
      (firstInvalid === "name" ? nameInput : emailInput).current?.focus();
      return;
    }

    booking.mutate(tidied, {
      onSuccess: onBooked,
      onError: (error) => {
        if (isRefusal(error)) onSlotUnavailable();
      },
    });
  }

  const bind = (field: Field) => ({
    name: field,
    value: details[field],
    error: problems[field],
    required: true,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
      setDetails({ ...details, [field]: event.target.value }),
  });

  return (
    <section aria-labelledby={headingId}>
      <h2 className="step__heading" id={headingId} ref={heading} tabIndex={-1}>
        {t.yourDetails}
      </h2>

      <div className="summary">
        <p className="summary__time">{slotLabel}</p>
        <Button variant="link" onClick={onChangeTime} disabled={booking.isPending}>
          {t.changeTime}
        </Button>
      </div>

      {/* noValidate: the messages below replace the browser's own bubbles, which
          cannot be styled and are announced inconsistently by screen readers. */}
      <form className="form" noValidate onSubmit={handleSubmit}>
        <TextField
          {...bind("name")}
          ref={nameInput}
          label={t.studentName}
          hint={t.studentNameHint}
          type="text"
          autoComplete="name"
        />
        <TextField
          {...bind("email")}
          ref={emailInput}
          label={t.email}
          hint={t.emailHint}
          type="email"
          autoComplete="email"
          inputMode="email"
        />

        {booking.isError && !isRefusal(booking.error) && (
          <p className="form__error" role="alert">
            {booking.error instanceof ApiError && booking.error.status === 422
              ? t.serverRejected
              : t.couldNotConfirm}
          </p>
        )}

        <Button type="submit" wide busy={booking.isPending}>
          {booking.isPending ? t.submitting : t.submit}
        </Button>
      </form>
    </section>
  );
}
