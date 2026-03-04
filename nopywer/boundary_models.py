"""Boundary schemas for parsing external QGIS/spreadsheet-like values.

When available, Pydantic is used for richer parsing/coercion errors. In limited
QGIS runtimes where Pydantic cannot import cleanly, a local validation fallback
keeps behavior deterministic.
"""

from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - environment-dependent import path
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
except Exception:  # pragma: no cover - fallback for constrained QGIS runtimes
    BaseModel = None
    ConfigDict = None
    Field = None
    ValidationError = ValueError
    field_validator = None


BoundaryValidationError = ValidationError


if BaseModel is not None:

    class CableFeatureBoundary(BaseModel):
        """Validated cable metadata parsed from QGIS features."""

        model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

        length: float = Field(gt=0)
        area: float = Field(gt=0)
        plugs_and_sockets: float = Field(gt=0)
        layer_name: str = Field(min_length=1)
        feature_id: int = Field(ge=0)
        coordinates: list[Any]

        @field_validator("coordinates")
        @classmethod
        def _validate_coordinates(cls, value: list[Any]) -> list[Any]:
            if not isinstance(value, list):
                raise TypeError("coordinates must be a list")
            if len(value) < 2:
                raise ValueError("coordinates must contain at least two points")
            return value


    class LoadFeatureBoundary(BaseModel):
        """Validated load metadata parsed from QGIS features."""

        model_config = ConfigDict(
            extra="forbid", str_strip_whitespace=True, arbitrary_types_allowed=True
        )

        name: str = Field(min_length=1)
        coordinates: Any

        @field_validator("name")
        @classmethod
        def _normalize_name(cls, value: str) -> str:
            out = value.lower().replace("\n", " ").replace("  ", " ").strip()
            if not out:
                raise ValueError("load name cannot be empty")
            return out

else:

    def _normalize_name(value: Any) -> str:
        if not isinstance(value, str):
            raise BoundaryValidationError(f"name must be str, got {type(value)}")
        out = value.lower().replace("\n", " ").replace("  ", " ").strip()
        if not out:
            raise BoundaryValidationError("load name cannot be empty")
        return out


    @dataclass(slots=True)
    class CableFeatureBoundary:
        length: float
        area: float
        plugs_and_sockets: float
        layer_name: str
        feature_id: int
        coordinates: list[Any]

        @classmethod
        def model_validate(cls, data: dict[str, Any]) -> "CableFeatureBoundary":
            try:
                length = float(data["length"])
                area = float(data["area"])
                plugs_and_sockets = float(data["plugs_and_sockets"])
                layer_name = str(data["layer_name"]).strip()
                feature_id = int(data["feature_id"])
                coordinates = data["coordinates"]
            except Exception as exc:
                raise BoundaryValidationError(f"invalid cable payload: {exc}") from exc

            if length <= 0:
                raise BoundaryValidationError("length must be > 0")
            if area <= 0:
                raise BoundaryValidationError("area must be > 0")
            if plugs_and_sockets <= 0:
                raise BoundaryValidationError("plugs_and_sockets must be > 0")
            if not layer_name:
                raise BoundaryValidationError("layer_name cannot be empty")
            if feature_id < 0:
                raise BoundaryValidationError("feature_id must be >= 0")
            if (not isinstance(coordinates, list)) or (len(coordinates) < 2):
                raise BoundaryValidationError(
                    "coordinates must be a list with at least two points"
                )

            return cls(
                length=length,
                area=area,
                plugs_and_sockets=plugs_and_sockets,
                layer_name=layer_name,
                feature_id=feature_id,
                coordinates=coordinates,
            )


    @dataclass(slots=True)
    class LoadFeatureBoundary:
        name: str
        coordinates: Any

        @classmethod
        def model_validate(cls, data: dict[str, Any]) -> "LoadFeatureBoundary":
            name = _normalize_name(data.get("name", None))
            return cls(name=name, coordinates=data.get("coordinates", None))
