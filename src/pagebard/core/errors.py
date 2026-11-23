"""Errors whose message can be shown to the user as-is (pt-BR)."""

from pagebard.core.i18n import _


class PagebardError(Exception):
    """An expected failure. ``str(error)`` is the user-facing message."""


def user_message(exc: BaseException) -> str:
    if isinstance(exc, PagebardError):
        return str(exc)
    return _("Something unexpected went wrong. Technical detail: {detail}").format(detail=exc)
