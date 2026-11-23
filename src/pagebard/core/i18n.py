"""Translations. The source is written in English; other languages come from
the .po files in pagebard/locale (standard gettext catalogs, read as they are:
there is no compile step).

The language is chosen once, when the program starts: many texts are module
constants, built when their module is imported.
"""

import ast
import gettext
import os
import re
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
SOURCE_LANGUAGE = "en"
ENVIRONMENT_VARIABLE = "PAGEBARD_LANGUAGE"

_PLURAL_FORMS = re.compile(r"plural\s*=\s*([^;]+)")
_COMMA_DECIMAL = {"pt_BR", "es"}

_language = SOURCE_LANGUAGE
_messages: dict[str, str] = {}
_plurals: dict[str, list[str]] = {}
_plural_index = lambda n: int(n != 1)  # noqa: E731  (English rule; replaced per catalog)


def available_languages() -> list[str]:
    """Codes that can be used, e.g. ["en", "es", "pt_BR"]."""
    return sorted([SOURCE_LANGUAGE, *(path.stem for path in LOCALE_DIR.glob("*.po"))])


def match_language(code: str | None) -> str | None:
    """The available language that serves a locale code like "pt_PT.UTF-8"."""
    if not code:
        return None
    code = code.split(".")[0].split("@")[0].replace("-", "_")
    available = available_languages()
    if code in available:
        return code
    family = code.split("_")[0].lower()
    for candidate in available:
        if candidate.split("_")[0].lower() == family:
            return candidate
    return None


def system_language() -> str:
    """Language asked for by the environment; English when none is available."""
    codes: list[str] = []
    codes += [part for part in os.environ.get("LANGUAGE", "").split(":") if part]
    codes += [os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG")]
    for code in codes:
        found = match_language(code)
        if found:
            return found
    return SOURCE_LANGUAGE


def set_language(code: str | None = None) -> str:
    """Switch to a language; None means PAGEBARD_LANGUAGE, else the system's."""
    global _language, _messages, _plurals, _plural_index
    chosen = (
        match_language(code)
        or match_language(os.environ.get(ENVIRONMENT_VARIABLE))
        or system_language()
    )
    messages: dict[str, str] = {}
    plurals: dict[str, list[str]] = {}
    rule = "n != 1"
    if chosen != SOURCE_LANGUAGE:
        messages, plurals = read_po(LOCALE_DIR / f"{chosen}.po")
        found = _PLURAL_FORMS.search(messages.get("", ""))
        if found:
            rule = found.group(1)
    _language, _messages, _plurals = chosen, messages, plurals
    _plural_index = gettext.c2py(rule)
    return chosen


def language() -> str:
    return _language


def _(message: str) -> str:
    """The message in the current language (itself when there is no translation)."""
    return _messages.get(message) or message


def ngettext(singular: str, plural: str, count: int) -> str:
    """Like `_`, for a message that depends on a count."""
    forms = _plurals.get(singular)
    if forms:
        index = int(_plural_index(count))
        if index < len(forms) and forms[index]:
            return forms[index]
    return singular if count == 1 else plural


def N_(message: str) -> str:
    """Marks a text for translation without translating it here."""
    return message


def decimal(value: float, digits: int = 1) -> str:
    """A number the way the current language writes it: 1.5 or 1,5."""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if _language in _COMMA_DECIMAL else text


def read_po(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Parse a .po file into ({msgid: msgstr}, {msgid: [plural forms]}).

    The header is the entry with the empty msgid.
    """
    messages: dict[str, str] = {}
    plurals: dict[str, list[str]] = {}
    entry: dict[str, str] = {}
    field = None

    def flush() -> None:
        if "msgid" not in entry:
            return
        msgid = entry["msgid"]
        if "msgid_plural" in entry:
            indexes = sorted(
                int(key[7:-1]) for key in entry if key.startswith("msgstr[")
            )
            plurals[msgid] = [entry[f"msgstr[{index}]"] for index in indexes]
        elif entry.get("msgstr") or msgid == "":
            messages[msgid] = entry.get("msgstr", "")

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line:
                flush()
                entry, field = {}, None
            continue
        if line.startswith('"'):
            if field is not None:
                entry[field] += ast.literal_eval(line)
            continue
        keyword, _space, rest = line.partition(" ")
        if keyword == "msgid" and "msgid" in entry:  # entries not separated by a blank line
            flush()
            entry = {}
        field = keyword
        entry[field] = ast.literal_eval(rest)
    flush()
    return messages, plurals


set_language()
