import { Link } from "react-router";

import { Button, Notice } from "../../ui";

interface BookingConfirmationProps {
  /** The booked time, already formatted for the visitor. */
  slotLabel: string;
  tutorName: string;
  lessonMinutes: number;
  /** Lets the visitor come back to cancel. Shown as a link they can keep. */
  manageToken: string;
  onBookAnother: () => void;
}

export function BookingConfirmation({
  slotLabel,
  tutorName,
  lessonMinutes,
  manageToken,
  onBookAnother,
}: BookingConfirmationProps) {
  return (
    // Moving focus here makes a screen reader announce the result of the form.
    <Notice tone="success" title="You’re booked" focusOnMount>
      <p className="notice__lead">{slotLabel}</p>
      <p>
        {lessonMinutes}-minute lesson with {tutorName}.
      </p>
      <p>
        {/* The token is in the fragment, which browsers do not send to servers. */}
        <Link className="link" to={{ pathname: "/booking", hash: `token=${manageToken}` }}>
          View or cancel this booking
        </Link>
      </p>
      <p>
        Save that link: confirmation emails are not sent yet, and it is the only way to cancel
        online.
      </p>
      <Button onClick={onBookAnother}>Book another lesson</Button>
    </Notice>
  );
}
