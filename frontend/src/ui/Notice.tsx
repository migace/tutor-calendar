import { useEffect, useId, useRef, type ReactNode } from "react";

interface NoticeProps {
  title: string;
  /**
   * `problem` and `warning` interrupt a screen reader (role="alert"). `success`
   * and `neutral` do not; move focus to them with `focusOnMount` when they
   * replace what the user was looking at.
   */
  tone?: "neutral" | "success" | "warning" | "problem";
  /** Heading level of the title, to fit the page outline. */
  level?: 1 | 2;
  /** Move keyboard focus to the title when the notice appears. */
  focusOnMount?: boolean;
  children?: ReactNode;
}

export function Notice({
  title,
  tone = "neutral",
  level = 2,
  focusOnMount = false,
  children,
}: NoticeProps) {
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const Heading = level === 1 ? "h1" : "h2";
  const interrupts = tone === "problem" || tone === "warning";

  useEffect(() => {
    if (focusOnMount) heading.current?.focus();
  }, [focusOnMount]);

  return (
    <section
      className={`notice notice--${tone}`}
      role={interrupts ? "alert" : undefined}
      aria-labelledby={titleId}
    >
      <Heading
        className="notice__title"
        id={titleId}
        ref={heading}
        tabIndex={focusOnMount ? -1 : undefined}
      >
        {title}
      </Heading>
      {children}
    </section>
  );
}
