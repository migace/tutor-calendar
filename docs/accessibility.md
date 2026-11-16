# Accessibility

The target is WCAG 2.2 level AA. This page says what was checked, how, what was
found, and what has not been checked. The last part matters most: passing an
automated check is not the same as being usable.

## What is checked on every commit

`frontend/src/a11y.test.tsx` runs in CI.

- **Every screen through axe-core**, in the states where things go wrong: forms
  showing their errors, a confirmation question open, an error page, a table of
  figures, and one screen in Polish. axe looks for mechanical failures such as a
  control with no name, a broken ARIA reference, a heading out of order or a
  table without headers.
- **One `main` landmark, one top-level heading and a page title** on each of the
  ten routes.
- **Colour contrast, computed from the design tokens** in both the light and the
  dark theme: 4.5:1 for every pairing of text and background the stylesheet
  uses, 3:1 for field borders and the focus ring. axe cannot measure colours
  without a real layout, so this is done from the stylesheet itself. A new
  colour that is too pale fails the build.

Three deliberate faults were introduced to make sure these tests can fail: a
time field without a name, paler secondary text, and a skip link that follows
its own address. Each was caught.

## What was built in, and tested as behaviour

- **Forms.** Every field has a visible label. Hints and error messages are tied
  to their field with `aria-describedby`, and a field with an error is marked
  `aria-invalid`. On a failed submit, focus goes to the first field with a
  problem. The browser's own validation bubbles are turned off because they
  cannot be styled and are announced inconsistently.
- **Focus when the page changes under the user.** Moving from the list of times
  to the form, getting a confirmation, or being sent back because a time was
  taken each move focus to the heading of what appeared, so a screen reader
  says where the user now is.
- **Irreversible actions ask first, in place.** There is no modal dialog and so
  no focus trap to get wrong. When the question appears, focus goes to the
  answer that changes nothing; backing out returns it to where it was.
- **Status and errors.** Results that do not move focus are announced through
  `role="status"`; things that went wrong through `role="alert"`.
- **Keyboard.** Every control is a native button, link or input.
- **Language.** `<html lang>` follows the language in use, and each name in the
  language switch is marked with its own language so it is pronounced correctly.
- **Target size.** Buttons and standalone links are at least 44 by 44 CSS pixels.
- **Motion.** The only animation, a loading pulse, stops under
  `prefers-reduced-motion`.
- **Colour is never the only signal.** A cancelled lesson is struck through and
  labelled; time owed is written out as "to pay for", not just shown in red.

## What the audit found

| Finding | Fix |
|---|---|
| The "nothing at this address" page had no title, so the browser tab kept the previous one. | It has a title, and a test checks every route for one. |
| Text-style buttons standing on their own ("Remove", "Change time") had a 24-pixel-high target. | They now have the full 44 pixels. Links inside a sentence keep the height of their line, which WCAG allows. |
| There was no way to jump past the banner and the panel's navigation. | A skip link is the first thing on every page. It moves focus without changing the address, because the booking and statement pages keep a token in the address fragment that `#content` would have replaced. A test checks that the token survives. |

axe itself reported no violations on any screen.

## What has not been checked

- **No one has used the application with a screen reader.** Roles, names and
  focus order are asserted in tests, which is not the same as listening to it
  with NVDA, JAWS or VoiceOver. This is the largest gap.
- **No testing with users who have disabilities.**
- **Zoom and reflow were checked at 375 pixels wide only**, by measuring for
  horizontal overflow, not at 320 pixels or at 400 % zoom.
- **The time and date fields are the browser's own.** Their accessibility is
  whatever the browser provides, which varies.
- **E-mail is plain text**, which is accessible, but in English only.
