"""Errors whose message can be shown to the user as-is (pt-BR)."""


class LeitorError(Exception):
    """An expected failure. ``str(error)`` is the user-facing message."""


def user_message(exc: BaseException) -> str:
    if isinstance(exc, LeitorError):
        return str(exc)
    return f"Ocorreu um erro inesperado. Detalhe técnico: {exc}"
