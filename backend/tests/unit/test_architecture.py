"""The dependency rules from ADR 0001, enforced.

Inner layers never import outer ones, the calendar knows nothing about money,
and the adapters that run in production never lean on the fakes.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = "tutor_calendar"
SOURCE = Path(__file__).parents[2] / "src" / PACKAGE

FRAMEWORKS = {"fastapi", "starlette", "sqlalchemy", "alembic", "pydantic", "pydantic_settings"}
FAKES = {f"{PACKAGE}.adapters.{path.stem}" for path in (SOURCE / "adapters").glob("in_memory_*.py")}
# What the code under each folder must not import.
FORBIDDEN = {
    "domain": FRAMEWORKS | {f"{PACKAGE}.{layer}" for layer in ("application", "adapters", "api")},
    "application": FRAMEWORKS | {f"{PACKAGE}.{layer}" for layer in ("adapters", "api")},
    # Billing charges for lessons, so it reads the calendar. The calendar must
    # keep working with billing taken out.
    "domain/scheduling": {f"{PACKAGE}.domain.billing"},
    # A fake is a test double. Code that runs in production borrowing from one
    # would make the double part of the product.
    "adapters/postgres": FAKES,
}


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            # ``from package import module`` names the module in the second half.
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def violates(module: str, forbidden: set[str]) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in forbidden)


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_code_imports_only_what_it_may(layer: str) -> None:
    files = sorted((SOURCE / layer).rglob("*.py"))
    assert files, f"no source files found under {layer!r}"

    violations = {
        f"{path.relative_to(SOURCE).as_posix()} imports {module}"
        for path in files
        for module in imported_modules(path)
        if violates(module, FORBIDDEN[layer])
    }

    assert not violations


def test_the_fakes_are_found() -> None:
    # The rule about fakes is only as good as this list.
    assert len(FAKES) >= 4
