import { useEffect, useRef } from "react";

interface BookingConfirmationProps {
  /** The booked time, already formatted for the visitor. */
  slotLabel: string;
  tutorName: string;
  lessonMinutes: number;
  onBookAnother: () => void;
}

export function BookingConfirmation({
  slotLabel,
  tutorName,
  lessonMinutes,
  onBookAnother,
}: BookingConfirmationProps) {
  const heading = useRef<HTMLHeadingElement>(null);

  // Moving focus here makes a screen reader announce the result of the form.
  useEffect(() => heading.current?.focus(), []);

  return (
    <section className="notice notice--success" aria-labelledby="booked-heading">
      <h2 className="notice__title" id="booked-heading" ref={heading} tabIndex={-1}>
        You&rsquo;re booked
      </h2>
      <p className="notice__lead">{slotLabel}</p>
      <p>
        {lessonMinutes}-minute lesson with {tutorName}.
      </p>
      <p>Make a note of the time: confirmation emails are not sent yet.</p>
      <button type="button" className="button" onClick={onBookAnother}>
        Book another lesson
      </button>
    </section>
  );
}
