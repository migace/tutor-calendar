import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button, Notice, TextField } from ".";

describe("Button", () => {
  it("does not submit a form unless asked to", async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Button>Cancel</Button>
        <Button type="submit">Save</Button>
      </form>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSubmit).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("cannot be pressed while busy and says it is busy", async () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Saving…
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Saving…" });
    await userEvent.click(button);

    expect(onClick).not.toHaveBeenCalled();
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});

describe("TextField", () => {
  it("ties the label and the hint to the input", () => {
    render(<TextField label="Email address" hint="We only use it to sign you in." />);

    const input = screen.getByLabelText("Email address");
    expect(input).toHaveAccessibleDescription("We only use it to sign you in.");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("marks the input invalid and reads the error after the hint", () => {
    render(<TextField label="Email address" hint="A hint." error="Enter an email address." />);

    const input = screen.getByLabelText("Email address");
    expect(input).toBeInvalid();
    expect(input).toHaveAccessibleDescription("A hint. Enter an email address.");
  });

  it("gives every field its own ids", () => {
    render(
      <>
        <TextField label="First" hint="One" />
        <TextField label="Second" hint="Two" />
      </>,
    );

    expect(screen.getByLabelText("First")).toHaveAccessibleDescription("One");
    expect(screen.getByLabelText("Second")).toHaveAccessibleDescription("Two");
  });
});

describe("Notice", () => {
  it("interrupts a screen reader only when something went wrong", () => {
    render(
      <>
        <Notice tone="problem" title="Could not save" />
        <Notice tone="success" title="Saved" />
      </>,
    );

    expect(screen.getByRole("alert")).toHaveAccessibleName("Could not save");
    expect(screen.getByRole("region", { name: "Saved" })).toBeInTheDocument();
  });

  it("can take focus when it replaces what the user was looking at", () => {
    render(<Notice tone="success" title="You’re booked" focusOnMount />);

    expect(screen.getByRole("heading", { name: "You’re booked" })).toHaveFocus();
  });
});
