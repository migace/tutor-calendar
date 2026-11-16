import { Link } from "react-router";

import { useT } from "../../i18n";
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
  const t = useT().booking;
  return (
    // Moving focus here makes a screen reader announce the result of the form.
    <Notice tone="success" title={t.bookedTitle} focusOnMount>
      <p className="notice__lead">{slotLabel}</p>
      <p>{t.lessonWith(lessonMinutes, tutorName)}</p>
      <p>
        {/* The token is in the fragment, which browsers do not send to servers. */}
        <Link className="link" to={{ pathname: "/booking", hash: `token=${manageToken}` }}>
          {t.viewOrCancel}
        </Link>
      </p>
      <p>{t.saveLink}</p>
      <Button onClick={onBookAnother}>{t.bookAnother}</Button>
    </Notice>
  );
}
