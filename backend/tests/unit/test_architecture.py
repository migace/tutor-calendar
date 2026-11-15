"""The dependency rule from ADR 0001, enforced: inner layers never import outer ones."""

import ast
from pathlib import Path

import pytest

PACKAGE = "tutor_calendar"
SOURCE = Path(__file__).parents[2] / "src" / PACKAGE

FRAMEWORKS = {"fastapi", "starlette", "sqlalchemy", "alembic", "pydantic", "pydantic_settings"}
FORBIDDEN = {
    "domain": FRAMEWORKS | {f"{PACKAGE}.{layer}" for layer in ("application", "adapters", "api")},
    "application": FRAMEWORKS | {f"{PACKAGE}.{layer}" for layer in ("adapters", "api")},
}


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def violates(module: str, forbidden: set[str]) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in forbidden)


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_only_depends_inwards(layer: str) -> None:
    files = sorted((SOURCE / layer).rglob("*.py"))
    assert files, f"no source files found for layer {layer!r}"

    violations = {
        f"{path.relative_to(SOURCE).as_posix()} imports {module}"
        for path in files
        for module in imported_modules(path)
        if violates(module, FORBIDDEN[layer])
    }

    assert not violations
