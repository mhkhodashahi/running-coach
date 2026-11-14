"""Reuse identical calculations only within an explicitly bounded render."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar, cast

P = ParamSpec("P")
T = TypeVar("T")
_CACHE: ContextVar[dict[tuple, object] | None] = ContextVar("metric_calculations", default=None)


@contextmanager
def calculation_scope() -> Iterator[None]:
    """Never retain athlete data or computed results across requests."""
    if _CACHE.get() is not None:
        yield
        return
    token = _CACHE.set({})
    try:
        yield
    finally:
        _CACHE.reset(token)


def memoized_calculation(function: Callable[P, T]) -> Callable[P, T]:
    """Cache successful, read-only computations with hashable inputs in this scope."""
    @wraps(function)
    def run(*args: P.args, **kwargs: P.kwargs) -> T:
        cache = _CACHE.get()
        if cache is None:
            return function(*args, **kwargs)
        key = (function, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = function(*args, **kwargs)
        return cast(T, cache[key])

    return run
