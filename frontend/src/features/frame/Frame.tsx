import { LANGUAGES, setLanguage, useLanguage, useT } from "../../i18n";
import { CalendarIcon } from "./icons";

/** The product's name and mark. Not a link: there is no home page to go back to yet. */
export function Brand() {
  const t = useT().common;
  return (
    <div className="brand">
      <span className="brand__mark">
        <CalendarIcon />
      </span>
      <span className="brand__name">{t.siteName}</span>
    </div>
  );
}

export function LanguageSwitch() {
  const t = useT().common;
  const language = useLanguage();
  return (
    <div className="language" role="group" aria-label={t.language}>
      {LANGUAGES.map(({ code, name }) => (
        <button
          key={code}
          type="button"
          className="language__option"
          // Each name is in its own language, and is announced that way.
          lang={code}
          aria-pressed={language === code}
          onClick={() => setLanguage(code)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}

/** The top of every page outside the tutor's panel. */
export function SiteHeader() {
  return (
    <header className="site-header">
      <Brand />
      <LanguageSwitch />
    </header>
  );
}
