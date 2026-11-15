"""Request-local planning budget. Never changes quote or approval authority."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import math
import time


class PlanningTimeout(RuntimeError):
    pass


@dataclass
class Budget:
    deadline: float
    prepared: object = None


_current = ContextVar('recipe_planning_budget', default=None)


@contextmanager
def scope(g):
    if _current.get() is not None:
        yield _current.get()
        return
    try:
        seconds = float(g.setting('AIMO_PLANNING_SECONDS', '180'))
        if not math.isfinite(seconds) or not 30 <= seconds <= 600:
            raise ValueError
    except ValueError:
        raise RuntimeError('Recipe planning configuration: AIMO_PLANNING_SECONDS must be 30–600 seconds.') from None
    budget = Budget(time.monotonic() + seconds)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def remaining(default=600):
    budget = _current.get()
    return max(0, budget.deadline - time.monotonic()) if budget else default


def check(stage='planning', reserve=0):
    if remaining() <= reserve:
        raise PlanningTimeout('Recipe planning time budget reached during '+stage+'. Saved checked items are retained when available. No supplier order was sent.')


def timeout(default):
    check()
    return max(.01, min(default, remaining()))


def checkpoint(prepared):
    budget = _current.get()
    if budget:
        budget.prepared = deepcopy(prepared)


@contextmanager
def lock(mutex):
    if _current.get() is None:
        with mutex:
            yield
        return
    check('supplier queue')
    if not mutex.acquire(timeout=remaining()):
        raise PlanningTimeout('Recipe planning time budget reached waiting for the supplier queue. No order was sent.')
    try:
        yield
    finally:
        mutex.release()


def bounded(g):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            with scope(g):
                return fn(*args, **kwargs)
        return run
    return decorate
