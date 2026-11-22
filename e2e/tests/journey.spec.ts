import { expect } from "@playwright/test";

import { mailSentTo, NAMES, newStudent, test } from "./journey";

/**
 * The one path through the whole product: the built web app, the API it is
 * served by, PostgreSQL, the worker and the mail it sends.
 *
 * It never names a date. It reads the day and the time it picked off the
 * booking page and looks for the same words on the pages that follow, so it
 * does not matter on which day or at what hour it runs.
 */
test("a visitor books a lesson, the tutor finds it, and the link in the e-mail gives the time back", async ({
  page,
  request,
  language,
  mailpitURL,
  baseURL,
}) => {
  const t = NAMES[language];
  const student = newStudent();
  const exact = (name: string) => ({ name, exact: true });

  // Filled in while booking, read by every step after it.
  let day = ""; // the day's button: "Thursday 3 December, 4 free times"
  let time = ""; // the time's button: "Thursday 3 December, 18:00"
  let lesson = ""; // the lesson in full: "Thursday 3 December, 18:00–19:00"
  let hours = ""; // "18:00–19:00"

  await test.step("the visitor picks a free time", async () => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/book\/demo$/);

    const choice = page.getByRole("button", exact(t.languageName));
    await expect(choice, "the browser asks for the other language").toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await choice.click();
    await expect(choice).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("html")).toHaveAttribute("lang", language);
    await expect(page.getByRole("heading", { level: 1, ...exact("Demo Tutor") })).toBeVisible();

    // Not the first day: its earliest time may slip inside the notice period
    // between loading the page and booking. Not the last: the two weeks on
    // offer end at an instant, so that day can gain a time while this runs.
    const days = page.getByRole("group", exact(t.pickDay)).getByRole("button");
    await expect(days.first()).toBeVisible();
    const offered = await days.evaluateAll((all) => all.map((one) => one.ariaLabel ?? ""));
    expect(offered.length, "days with free times").toBeGreaterThanOrEqual(3);
    day = offered.at(-2)!;
    const date = day.slice(0, day.lastIndexOf(", "));

    await page.getByRole("button", exact(day)).click();
    const times = page.getByRole("region", exact(date)).getByRole("button");
    time = (await times.last().getAttribute("aria-label"))!;
    await page.getByRole("button", exact(time)).click();
    await expect(page.getByRole("button", exact(time))).toHaveAttribute("aria-pressed", "true");

    const status = page.getByRole("status").filter({ hasText: t.selected });
    await expect(status).toContainText(time);
    lesson = (await status.textContent())!.replace(t.selected, "");
    hours = lesson.slice(lesson.lastIndexOf(", ") + 2);
    expect(hours).toMatch(/^\d\d:\d\d–\d\d:\d\d$/);

    await page.getByRole("button", exact(t.continue)).click();
  });

  await test.step("gives a name and an address, and is told it is booked", async () => {
    await expect(page.getByRole("heading", exact(t.yourDetails))).toBeFocused();
    await page.getByRole("textbox", exact(t.studentName)).fill(student.name);
    await page.getByRole("textbox", exact(t.email)).fill(student.email);
    await page.getByRole("button", exact(t.bookLesson)).click();

    await expect(page.getByRole("heading", exact(t.booked))).toBeFocused();
    await expect(page.getByRole("region", exact(t.booked))).toContainText(lesson);

    // The day no longer has as many free times as it had.
    await page.getByRole("button", exact(t.bookAnother)).click();
    await expect(page.getByRole("group", exact(t.pickDay))).toBeVisible();
    await expect(page.getByRole("button", exact(day))).toHaveCount(0);
  });

  await test.step("the tutor enters the panel and finds the lesson in its week", async () => {
    await page.getByRole("link", exact(t.tutorsSide)).click();
    await page.getByRole("button", exact(t.enterPanel)).click();
    await expect(page).toHaveURL(/\/panel$/);

    // The lesson is one or two weeks away. Which, depends on today.
    const week = page.getByRole("heading", { level: 1 });
    const address = page.getByRole("link", exact(student.email));
    await expect(week).toBeVisible();
    for (let ahead = 0; ahead < 3 && (await address.count()) === 0; ahead += 1) {
      const shown = (await week.textContent())!;
      await page
        .getByRole("navigation", exact(t.weeks))
        .getByRole("link", exact(t.next))
        .click();
      await expect(week).not.toHaveText(shown);
    }

    // "Thursday 3 December" on the booking page is "Thursday 3 Dec" here.
    const [, weekday, dayOfMonth] = /^(\p{L}+),? (\d+) /u.exec(day)!;
    const onItsDay = page
      .getByRole("listitem", { name: new RegExp(`^${weekday} ${dayOfMonth} `) })
      .getByRole("listitem")
      .filter({ has: address });
    await expect(onItsDay).toContainText(hours);
    await expect(onItsDay).toContainText(student.name);
    // The button says whose lesson it cancels to someone who cannot see the row.
    await expect(onItsDay.getByRole("button", exact(t.cancel))).toHaveAccessibleDescription(
      `${hours} ${student.name}`,
    );
  });

  await test.step("opens the student from the list and reads the statement", async () => {
    await page.getByRole("navigation", exact(t.panel)).getByRole("link", exact(t.students)).click();
    await page.getByRole("link", exact(student.name)).click();
    await expect(page.getByRole("heading", { level: 1, ...exact(student.name) })).toBeVisible();

    await expect(page.getByRole("radio", exact(t.package))).toBeChecked();
    await page.getByRole("textbox", exact(t.hours)).fill("2");
    await page.getByRole("button", exact(t.record)).click();

    // Nothing here names the month: a run at midnight on the last day would
    // otherwise read the wrong one.
    await expect(page.getByText(t.recorded, { exact: true })).toBeVisible();
    await expect(page.getByText(t.balance, { exact: true })).toBeVisible();
    await expect(
      page.getByRole("table", { name: t.statement }).getByRole("row", exact(t.closing)),
    ).toBeVisible();
  });

  await test.step("the link in the confirmation e-mail cancels the lesson", async () => {
    const mail = await mailSentTo(request, mailpitURL, student.email);
    expect(mail.subject).toBe("Your lesson with Demo Tutor is booked");
    expect(mail.text).toContain(`Hello ${student.name},`);
    // The e-mail gives the time on the tutor's clock, which is this browser's too.
    expect(mail.text).toContain(`, ${hours.slice(0, 5)} (Europe/Warsaw time)`);
    const [link] = /\S+\/booking#token=\S+/.exec(mail.text)!;
    expect(link.startsWith(`${baseURL}/booking#`), `${link} leads back to the application`).toBe(
      true,
    );

    await page.goto(link);
    await expect(page.getByText(t.lessonFor(student.name), { exact: false })).toBeVisible();
    await expect(page.getByRole("region", exact(t.yourLesson))).toContainText(lesson);
    await page.getByRole("button", exact(t.cancelLesson)).click();
    await page.getByRole("group", exact(t.askCancel)).getByRole("button", exact(t.yesCancel)).click();

    await expect(page.getByRole("heading", exact(t.cancelled))).toBeFocused();
    await expect(page.getByRole("region", exact(t.cancelled))).toContainText(lesson);
    await expect(page.getByText(t.cancelledInTime, { exact: true })).toBeVisible();
  });

  await test.step("and the time is free again", async () => {
    await page.goto("/book/demo");
    await page.getByRole("button", exact(day)).click();
    await expect(page.getByRole("button", exact(time))).toBeVisible();
  });
});
