"""Fallback test runner for environments without pytest.

Use `pytest` normally (`pip install -e '.[dev]' && pytest`). This exists only so
the suite can be executed where pytest cannot be installed. It implements just
the subset of the pytest API the tests use: fixtures, `raises`, `approx`, and
`mark.parametrize`.

    python3 dev/minirunner.py
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import shutil
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# --- minimal pytest shim ---------------------------------------------------


class _Approx:
    def __init__(self, expected: float, rel: float = 1e-6) -> None:
        self.expected = expected
        self.rel = rel

    def __eq__(self, other: object) -> bool:
        return abs(float(other) - self.expected) <= max(  # type: ignore[arg-type]
            self.rel * abs(self.expected), 1e-12
        )

    def __repr__(self) -> str:
        return f"approx({self.expected})"


class _ExcInfo:
    def __init__(self) -> None:
        self.value: BaseException | None = None


@contextlib.contextmanager
def _raises(expected):  # noqa: ANN001
    info = _ExcInfo()
    try:
        yield info
    except expected as exc:  # type: ignore[misc]
        info.value = exc
        return
    raise AssertionError(f"DID NOT RAISE {expected}")


def _fixture(func=None, **_kwargs):  # noqa: ANN001
    def wrap(f):  # noqa: ANN001
        f.__is_fixture__ = True
        return f

    return wrap(func) if func is not None else wrap


class _Mark:
    @staticmethod
    def parametrize(argnames, argvalues):  # noqa: ANN001
        names = [n.strip() for n in argnames.split(",")]

        def deco(func):  # noqa: ANN001
            func.__parametrize__ = (names, list(argvalues))
            return func

        return deco

    def __getattr__(self, _name: str):  # noqa: ANN001
        def deco(func=None, **_kw):  # noqa: ANN001
            return func if func is not None else (lambda f: f)

        return deco


shim = types.ModuleType("pytest")
shim.fixture = _fixture  # type: ignore[attr-defined]
shim.raises = _raises  # type: ignore[attr-defined]
shim.approx = _Approx  # type: ignore[attr-defined]
shim.mark = _Mark()  # type: ignore[attr-defined]
sys.modules["pytest"] = shim


# --- fixture resolution ----------------------------------------------------


class Resolver:
    def __init__(self, fixtures: dict) -> None:
        self.fixtures = fixtures

    async def resolve(self, name: str, cache: dict, finalizers: list):
        if name in cache:
            return cache[name]
        if name == "tmp_path":
            path = Path(tempfile.mkdtemp(prefix="twin-test-"))
            finalizers.append(lambda: shutil.rmtree(path, ignore_errors=True))
            cache[name] = path
            return path

        func = self.fixtures.get(name)
        if func is None:
            raise AssertionError(f"unknown fixture: {name}")

        kwargs = {}
        for param in inspect.signature(func).parameters:
            kwargs[param] = await self.resolve(param, cache, finalizers)

        if inspect.isasyncgenfunction(func):
            agen = func(**kwargs)
            value = await agen.__anext__()
            finalizers.append(_closer(agen))
        elif inspect.iscoroutinefunction(func):
            value = await func(**kwargs)
        elif inspect.isgeneratorfunction(func):
            gen = func(**kwargs)
            value = next(gen)
            finalizers.append(lambda g=gen: _drain(g))
        else:
            value = func(**kwargs)

        cache[name] = value
        return value


def _closer(agen):  # noqa: ANN001
    async def close():
        # Awaited inside the test's own loop; closing from a different loop
        # leaves the athrow task pending and noisy.
        with contextlib.suppress(StopAsyncIteration):
            await agen.__anext__()
        await agen.aclose()

    return close


def _drain(gen):  # noqa: ANN001
    with contextlib.suppress(StopIteration):
        next(gen)


# --- collection and execution ----------------------------------------------


def collect(module) -> list:  # noqa: ANN001
    out = []
    for name, obj in vars(module).items():
        if not name.startswith("test_") or not callable(obj):
            continue
        params = getattr(obj, "__parametrize__", None)
        if params:
            names, values = params
            for value in values:
                bound = value if isinstance(value, tuple) else (value,)
                out.append((f"{name}[{bound[0]}]", obj, dict(zip(names, bound))))
        else:
            out.append((name, obj, {}))
    return out


async def run_one(func, resolver: Resolver, extra: dict) -> None:
    cache: dict = {}
    finalizers: list = []
    kwargs = dict(extra)
    try:
        for param in inspect.signature(func).parameters:
            if param in kwargs:
                continue
            kwargs[param] = await resolver.resolve(param, cache, finalizers)
        result = func(**kwargs)
        if inspect.isawaitable(result):
            await result
    finally:
        for fin in reversed(finalizers):
            with contextlib.suppress(Exception):
                outcome = fin()
                if inspect.isawaitable(outcome):
                    await outcome


def main() -> int:
    import importlib

    conftest = importlib.import_module("tests.conftest")
    fixtures = {
        n: o
        for n, o in vars(conftest).items()
        if callable(o) and getattr(o, "__is_fixture__", False)
    }
    resolver = Resolver(fixtures)

    modules = sorted(
        p.stem for p in (ROOT / "tests").glob("test_*.py")
    )
    passed = failed = 0
    failures: list[tuple[str, str]] = []

    for mod_name in modules:
        module = importlib.import_module(f"tests.{mod_name}")
        for test_name, func, extra in collect(module):
            label = f"{mod_name}::{test_name}"
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run_one(func, resolver, extra))
            except Exception:
                failed += 1
                failures.append((label, traceback.format_exc()))
                print(f"F {label}")
            else:
                passed += 1
                print(f". {label}")
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

    print()
    for label, tb in failures:
        print("=" * 70)
        print(label)
        print(tb)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    (ROOT / "tests" / "__init__.py").touch()
    raise SystemExit(main())
