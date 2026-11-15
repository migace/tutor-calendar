import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { ApiError, type Booking, type Slot } from "../../api/client";
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

function check({ name, email }: StudentDetails): Problems {
  const problems: Problems = {};
  if (!name) {
    problems.name = "Enter the student's name.";
  } else if (name.length > MAX_NAME_LENGTH) {
    problems.name = `Use ${MAX_NAME_LENGTH} characters or fewer.`;
  }
  if (!email) {
    problems.email = "Enter an email address.";
  } else if (!LOOKS_LIKE_EMAIL.test(email)) {
    problems.email = "Enter an email address like name@example.com.";
  }
  return problems;
}

function describeFailure(error: Error): string {
  if (error instanceof ApiError && error.status === 422) {
    return "The server did not accept these details. Check the name and email address.";
  }
  return "We could not confirm your booking. You have not been booked twice: it is safe to try again.";
}

export function BookingForm({
  slug,
  slot,
  slotLabel,
  onBooked,
  onSlotUnavailable,
  onChangeTime,
}: BookingFormProps) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const inputs = useRef<Partial<Record<Field, HTMLInputElement | null>>>({});
  const [details, setDetails] = useState<StudentDetails>({ name: "", email: "" });
  const [problems, setProblems] = useState<Problems>({});
  const booking = useBookLesson(slug, slot);

  // This step replaces the list of times, so tell keyboard and screen reader
  // users where they are now.
  useEffect(() => heading.current?.focus(), []);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const tidied = { name: details.name.trim(), email: details.email.trim() };
    const found = check(tidied);
    setProblems(found);

    const firstInvalid = (["name", "email"] as const).find((field) => found[field]);
    if (firstInvalid) {
      inputs.current[firstInvalid]?.focus();
      return;
    }

    booking.mutate(tidied, {
      onSuccess: onBooked,
      onError: (error) => {
        if (error instanceof ApiError && error.status === 409) onSlotUnavailable();
      },
    });
  }

  function field(name: Field, label: string, hint: string, props: Record<string, string>) {
    const problem = problems[name];
    const hintId = `${id}-${name}-hint`;
    const problemId = `${id}-${name}-problem`;
    return (
      <div className="field">
        <label className="field__label" htmlFor={`${id}-${name}`}>
          {label}
        </label>
        <p className="field__hint" id={hintId}>
          {hint}
        </p>
        <input
          {...props}
          className="field__input"
          id={`${id}-${name}`}
          name={name}
          ref={(element) => {
            inputs.current[name] = element;
          }}
          value={details[name]}
          required
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${hintId} ${problemId}` : hintId}
          onChange={(event) => setDetails({ ...details, [name]: event.target.value })}
        />
        {problem && (
          <p className="field__problem" id={problemId}>
            {problem}
          </p>
        )}
      </div>
    );
  }

  return (
    <section aria-labelledby={`${id}-heading`}>
      <h2 className="step__heading" id={`${id}-heading`} ref={heading} tabIndex={-1}>
        Your details
      </h2>

      <div className="summary">
        <p className="summary__time">{slotLabel}</p>
        <button type="button" className="link" onClick={onChangeTime} disabled={booking.isPending}>
          Change time
        </button>
      </div>

      {/* noValidate: the messages below replace the browser's own bubbles, which
          cannot be styled and are announced inconsistently by screen readers. */}
      <form className="form" noValidate onSubmit={handleSubmit}>
        {field("name", "Student's name", "Who the lesson is for.", {
          type: "text",
          autoComplete: "name",
        })}
        {field("email", "Email address", "So the tutor can reach you about this lesson.", {
          type: "email",
          autoComplete: "email",
          inputMode: "email",
        })}

        {booking.isError && !(booking.error instanceof ApiError && booking.error.status === 409) && (
          <p className="form__error" role="alert">
            {describeFailure(booking.error)}
          </p>
        )}

        <button type="submit" className="button button--wide" disabled={booking.isPending}>
          {booking.isPending ? "Booking…" : "Book lesson"}
        </button>
      </form>
    </section>
  );
}
