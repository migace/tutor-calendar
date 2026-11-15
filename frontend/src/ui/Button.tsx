import type { ButtonHTMLAttributes, Ref } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `primary` for the one main action of a view, `secondary` for the rest, `link` for inline actions. */
  variant?: "primary" | "secondary" | "link";
  /** Stretch to the width of the container. */
  wide?: boolean;
  /** The action is in progress: the button is disabled and says so to assistive technology. */
  busy?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = "primary",
  wide = false,
  busy = false,
  type = "button",
  disabled,
  className,
  ...rest
}: ButtonProps) {
  const classes = [
    variant === "link" ? "link" : "button",
    variant === "secondary" && "button--secondary",
    wide && "button--wide",
    className,
  ];
  return (
    <button
      {...rest}
      // Not "submit" by default: a stray button inside a form should not submit it.
      type={type}
      className={classes.filter(Boolean).join(" ")}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
    />
  );
}
