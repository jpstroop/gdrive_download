"""Shared JSON type aliases used across the gdrive package."""

# Standard library imports
from typing import Union

type JSONPrimitive = Union[str, int, float, bool, None]
type JSONType = Union[dict[str, "JSONType"], list["JSONType"], JSONPrimitive]
type JSONDict = dict[str, JSONType]
type JSONList = list[JSONType]
