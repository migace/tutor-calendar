import { useEffect, useRef, useState } from "react";

import { Button } from "./Button";

interface ConfirmActionProps {
  /** The button that starts it, e.g. "Cancel lesson". */
  label: string;
  /** Asked before anything happens, e.g. "Cancel this lesson?". */
  question: string;
  /** The button that goes ahead, e.g. "Yes, cancel". */
  confirmLabel: string;
  /** The button that backs out, e.g. "No, keep it". */
  declineLabel: string;
  /** Names the thing acted on for screen readers, when the label alone is ambiguous. */
  describedBy?: string;
  busy?: boolean;
  onConfirm: () => void;
}

/**
 * A button for something that cannot be undone: it asks first, in place.
 *
 * No dialog, so nothing covers the page and nothing has to trap focus. When
 * the question appears, focus goes to the answer that changes nothing.
 */
export function ConfirmAction({
  label,
  question,
  confirmLabel,
  declineLabel,
  describedBy,
  busy = false,
  onConfirm,
}: ConfirmActionProps) {
  const [asking, setAsking] = useState(false);
  const decline = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const wasAsking = useRef(false);

  useEffect(() => {
    if (asking) decline.current?.focus();
    // Backing out puts focus where it was, not at the top of the page.
    else if (wasAsking.current) opener.current?.focus();
    wasAsking.current = asking;
  }, [asking]);

  if (!asking && !busy) {
    return (
      <Button
        ref={opener}
        variant="secondary"
        aria-describedby={describedBy}
        onClick={() => setAsking(true)}
      >
        {label}
      </Button>
    );
  }

  return (
    <div className="confirm" role="group" aria-label={question}>
      <p className="confirm__question">{question}</p>
      <Button busy={busy} aria-describedby={describedBy} onClick={onConfirm}>
        {confirmLabel}
      </Button>
      <Button ref={decline} variant="secondary" disabled={busy} onClick={() => setAsking(false)}>
        {declineLabel}
      </Button>
    </div>
  );
}
