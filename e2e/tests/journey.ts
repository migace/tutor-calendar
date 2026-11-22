import { expect, test as base, type APIRequestContext } from "@playwright/test";

export type Language = "en" | "pl";

export interface JourneyOptions {
  /** The language the visitor picks in the page. */
  language: Language;
  /** Where Mailpit, which catches the application's mail, serves its API. */
  mailpitURL: string;
}

export const test = base.extend<JourneyOptions>({
  language: ["en", { option: true }],
  mailpitURL: ["http://localhost:8025", { option: true }],
});

/**
 * What the journey reads and presses, by accessible name, in each language.
 *
 * Written out here and not imported from the web app's catalogues on purpose:
 * a name changed there by accident has to fail here.
 */
export const NAMES = {
  en: {
    languageName: "English",
    pickDay: "Pick a day",
    selected: "Selected: ",
    continue: "Continue",
    yourDetails: "Your details",
    studentName: "Student's name",
    email: "Email address",
    bookLesson: "Book lesson",
    booked: "You’re booked",
    bookAnother: "Book another lesson",
    tutorsSide: "See the tutor’s side",
    enterPanel: "Enter the demo tutor’s panel",
    panel: "Panel",
    weeks: "Weeks",
    next: "Next",
    cancel: "Cancel",
    students: "Students",
    statement: /^Lesson time in .+, with the balance before and after$/,
    package: "A package the student paid for",
    hours: "Hours",
    record: "Record",
    recorded: "Recorded +2 h.",
    balance: "Now: 2 h left",
    closing: "Balance at the end of the month 2 h",
    lessonFor: (student: string) => `Lesson for ${student}`,
    yourLesson: "Your lesson",
    cancelLesson: "Cancel lesson",
    askCancel: "Cancel this lesson?",
    yesCancel: "Yes, cancel",
    cancelled: "This lesson is cancelled",
    cancelledInTime: "It was cancelled in time and will not be charged.",
  },
  pl: {
    languageName: "Polski",
    pickDay: "Wybierz dzień",
    selected: "Wybrano: ",
    continue: "Dalej",
    yourDetails: "Twoje dane",
    studentName: "Imię i nazwisko ucznia",
    email: "Adres e-mail",
    bookLesson: "Zarezerwuj lekcję",
    booked: "Lekcja zarezerwowana",
    bookAnother: "Zarezerwuj kolejną lekcję",
    tutorsSide: "Zobacz panel korepetytora",
    enterPanel: "Wejdź do panelu korepetytora demo",
    panel: "Panel",
    weeks: "Tygodnie",
    next: "Następny",
    cancel: "Odwołaj",
    students: "Uczniowie",
    statement: /^Czas lekcji: .+, z saldem przed i po$/,
    package: "Pakiet opłacony przez ucznia",
    hours: "Godziny",
    record: "Zapisz",
    recorded: "Zapisano: +2 h.",
    balance: "Teraz: zostało 2 h",
    closing: "Saldo na koniec miesiąca 2 h",
    lessonFor: (student: string) => `Lekcja dla: ${student}`,
    yourLesson: "Twoja lekcja",
    cancelLesson: "Odwołaj lekcję",
    askCancel: "Odwołać tę lekcję?",
    yesCancel: "Tak, odwołaj",
    cancelled: "Ta lekcja jest odwołana",
    cancelledInTime: "Została odwołana na czas i nie jest płatna.",
  },
} as const satisfies Record<Language, unknown>;

/**
 * A student nobody has seen before, so a second run against the same database
 * finds its own lesson and its own mail and not the first run's.
 */
export function newStudent(): { name: string; email: string } {
  const tag = crypto.randomUUID().slice(0, 8);
  return { name: `Łucja Próbna ${tag}`, email: `lucja.${tag}@example.com` };
}

/**
 * The text of the one message sent to an address, once the worker has
 * delivered it. The worker empties the outbox every few seconds, so this waits.
 */
export async function mailSentTo(
  request: APIRequestContext,
  mailpitURL: string,
  address: string,
): Promise<{ subject: string; text: string }> {
  let mail = { subject: "", text: "" };
  await expect(async () => {
    const search = await request.get(`${mailpitURL}/api/v1/search`, {
      params: { query: `to:"${address}"` },
    });
    expect(search.ok(), "Mailpit answers").toBe(true);
    const { messages } = (await search.json()) as { messages: { ID: string }[] };
    expect(messages, `messages to ${address}`).toHaveLength(1);
    const message = await request.get(`${mailpitURL}/api/v1/message/${messages[0]!.ID}`);
    expect(message.ok(), "Mailpit hands the message over").toBe(true);
    const { Subject, Text } = (await message.json()) as { Subject: string; Text: string };
    mail = { subject: Subject, text: Text };
  }).toPass({ timeout: 30_000 });
  return mail;
}
