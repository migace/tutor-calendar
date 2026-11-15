import { Button, Notice } from "../../ui";

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
  return (
    // Moving focus here makes a screen reader announce the result of the form.
    <Notice tone="success" title="You’re booked" focusOnMount>
      <p className="notice__lead">{slotLabel}</p>
      <p>
        {lessonMinutes}-minute lesson with {tutorName}.
      </p>
      <p>Make a note of the time: confirmation emails are not sent yet.</p>
      <Button onClick={onBookAnother}>Book another lesson</Button>
    </Notice>
  );
}
