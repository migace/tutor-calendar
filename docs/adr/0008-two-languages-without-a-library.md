# ADR 0008: Two languages, as typed catalogs, without a library

Status: accepted · 2026-11-16

## Context

The product is for Polish tutors, and the repository is read in English. The
interface therefore needs both languages, with the visitor able to switch.

Polish is not a matter of swapping words. It has three plural forms (1 lekcja,
2 lekcje, 5 lekcji), word order that moves the variable part of a sentence, and
month names that change with the day in front of them. A sentence assembled
from translated fragments reads wrong in ways a translator of the fragments
cannot see.

## Decision

1. **Each language is one TypeScript object** with the same shape. The English
   catalog defines the type; the Polish one is declared to be of that type, so
   a missing or misspelled key is a compile error.
2. **A sentence with a variable part is a function**, not a template with a
   placeholder. Each language decides where the value goes and which form the
   words around it take. Polish plurals come from `Intl.PluralRules`.
3. **Dates, times and month names come from `Intl`**, in the locale that goes
   with the language. Mixing a browser's locale with the interface's language
   gives a Polish visitor "wtorek" in the middle of an English sentence.
4. **The language is detected once** from the browser, can be changed with a
   control at the foot of every page, and is remembered in local storage.
   `<html lang>` follows it.
5. **What the server says in words is not shown as is in Polish.** The API
   explains refusals in English. In English those explanations are shown; in
   Polish the interface gives its own sentence. The fixed notes the system
   writes on a statement ("Lesson cancelled late") are translated by lookup,
   and the tutor's own notes are shown as written.

## How this is verified

- The compiler checks that both catalogs have every key.
- A test walks both catalogs and fails if a Polish entry is identical to the
  English one, apart from three that are names.
- Polish plurals are tested for the numbers where the form changes: 1, 2, 4, 5,
  12, 22 and 25.
- A test switches a page to Polish and back and checks the sentences, the dates
  and `<html lang>`.

Every other frontend test runs in English, and none needed changing when the
strings moved into the catalog, which is what showed the move changed nothing.

## Alternatives considered

- **An i18n library** (react-i18next, FormatJS). They bring loading of catalogs
  on demand, tooling for translators and ICU message syntax. With two languages,
  one translator who is also the developer, and about 250 messages, they would
  add a dependency, a string-keyed lookup that the compiler cannot check, and a
  message syntax to learn, in exchange for things this project does not need.
  If a third language or an outside translator arrives, this decision should be
  revisited: plain objects do not scale to people who do not read TypeScript.
- **Letting the server pick the language** from `Accept-Language`. The server
  would then have to translate too, and the choice could not be changed without
  a request.
- **English only.** Not for a product whose users are Polish.

## Consequences

- Both languages ship in the one bundle. At this size that is a few kilobytes.
- Adding a sentence means adding it twice, and the compiler insists.
- E-mail is written by the server and is in English only. A tutor-level language
  setting would be the way to change that, and does not exist yet.
