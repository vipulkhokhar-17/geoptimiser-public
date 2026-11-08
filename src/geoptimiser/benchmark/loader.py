"""Load query and judgment sets from JSON, with errors that name the file."""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from geoptimiser.benchmark.models import JudgmentSet, QuerySet

M = TypeVar("M", bound=BaseModel)


class DatasetError(ValueError):
    """A dataset file is unreadable or invalid."""


def _load(path: Path, model: type[M]) -> M:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise DatasetError(f"{path}: cannot read ({type(exc).__name__})") from exc
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path}: invalid JSON at line {exc.lineno}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise DatasetError(f"{path}: {where}: {first['msg']}") from exc


def load_query_set(path: Path) -> QuerySet:
    return _load(path, QuerySet)


def load_judgment_set(path: Path) -> JudgmentSet:
    return _load(path, JudgmentSet)
