import { useId, type InputHTMLAttributes, type Ref } from "react";

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  /** Always-visible help below the label. */
  hint?: string;
  /** What is wrong with the current value. Its presence marks the field invalid. */
  error?: string;
  ref?: Ref<HTMLInputElement>;
}

/**
 * A labelled input. The label, hint and error are wired to the input, so a
 * screen reader announces all three when the field is focused.
 */
export function TextField({ label, hint, error, className, ref, ...input }: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(" ");

  return (
    <div className={["field", className].filter(Boolean).join(" ")}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {hint && (
        <p className="field__hint" id={hintId}>
          {hint}
        </p>
      )}
      <input
        {...input}
        ref={ref}
        id={id}
        className="field__input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      {error && (
        <p className="field__problem" id={errorId}>
          {error}
        </p>
      )}
    </div>
  );
}
