from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class RawOCRExportMapper:
    columns = ["JSON Path", "Value", "Value Type"]

    def map_rows(self, payload: dict[str, Any] | None) -> list[dict[str, str]]:
        if payload is None:
            return []

        rows: list[dict[str, str]] = []
        self._flatten(payload, "", rows)
        return rows

    def _flatten(self, value: Any, path: str, rows: list[dict[str, str]]) -> None:
        if isinstance(value, Mapping):
            if not value:
                rows.append(self._build_row(path or "$", "{}", "object"))
                return
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                self._flatten(child, child_path, rows)
            return

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if not value:
                rows.append(self._build_row(path or "$", "[]", "array"))
                return
            for index, child in enumerate(value):
                child_path = f"{path}[{index}]" if path else f"[{index}]"
                self._flatten(child, child_path, rows)
            return

        rows.append(self._build_row(path or "$", self._stringify(value), self._value_type(value)))

    def _build_row(self, path: str, value: str, value_type: str) -> dict[str, str]:
        return {
            "JSON Path": path,
            "Value": value,
            "Value Type": value_type,
        }

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _value_type(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "number"
        return "string"


raw_ocr_export_mapper = RawOCRExportMapper()
