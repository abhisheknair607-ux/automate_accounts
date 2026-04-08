from __future__ import annotations

import csv
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.services.extraction.providers.ocr_space_provider import OCRSpaceExtractionProvider


class TesseractExtractionProvider(OCRSpaceExtractionProvider):
    name = "tesseract"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings=settings or get_settings())
        self._version_cache: str | None = None

    def _provider_display_name(self) -> str:
        return "Tesseract"

    def _analysis_api_version(self) -> str:
        return self._tesseract_version()

    def _model_id(self) -> str:
        return (
            f"tesseract-{self._settings.tesseract_language}"
            f"-psm{self._settings.tesseract_page_seg_mode}"
        )

    def _pdf_render_dpi(self) -> int:
        return self._settings.tesseract_pdf_render_dpi

    def _max_image_side(self) -> int:
        return self._settings.tesseract_max_image_side

    def _max_image_bytes(self) -> int:
        return self._settings.tesseract_max_image_bytes

    def _ensure_configuration(self) -> None:
        if self._resolve_command() is None:
            raise RuntimeError(
                "Tesseract is selected but no runnable binary was found. "
                "Set TESSERACT_COMMAND to your installed tesseract executable path "
                "or add tesseract to PATH."
            )

    def _submit_ocr_request(self, image_bytes: bytes, page_number: int) -> dict[str, Any]:
        command = self._resolve_command()
        if command is None:
            self._ensure_configuration()
            raise AssertionError("Tesseract command resolution should have failed earlier.")

        temp_path = Path(self._temp_root()) / f"tesseract-ocr-{uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            input_path = temp_path / f"page-{page_number}.jpg"
            output_base = temp_path / f"page-{page_number}"
            input_path.write_bytes(image_bytes)

            args = [
                command,
                str(input_path),
                str(output_base),
                "-l",
                self._settings.tesseract_language,
                "--psm",
                str(self._settings.tesseract_page_seg_mode),
            ]
            if self._settings.tesseract_oem is not None:
                args.extend(["--oem", str(self._settings.tesseract_oem)])
            if self._settings.tesseract_data_dir:
                args.extend(["--tessdata-dir", str(self._settings.tesseract_data_dir)])
            args.extend(["tsv", "quiet"])

            try:
                subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=self._settings.tesseract_timeout_seconds,
                    check=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "Tesseract could not be started. "
                    "Set TESSERACT_COMMAND to the installed executable path."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Tesseract timed out on page {page_number} after "
                    f"{self._settings.tesseract_timeout_seconds} seconds."
                ) from exc
            except subprocess.CalledProcessError as exc:
                message = (exc.stderr or exc.stdout or "").strip()
                raise RuntimeError(
                    f"Tesseract failed on page {page_number}: {message or 'unknown OCR error'}"
                ) from exc

            text_path = output_base.with_suffix(".txt")
            tsv_path = output_base.with_suffix(".tsv")
            parsed_text = text_path.read_text(encoding="utf-8", errors="ignore").strip() if text_path.exists() else ""
            text_overlay = self._build_text_overlay(tsv_path)
            if not parsed_text:
                parsed_text = "\n".join(
                    line.get("LineText", "").strip()
                    for line in text_overlay.get("Lines", [])
                    if line.get("LineText")
                ).strip()
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

        return {
            "ParsedResults": [
                {
                    "ParsedText": parsed_text,
                    "TextOverlay": text_overlay,
                }
            ],
            "IsErroredOnProcessing": False,
        }

    def _resolve_command(self) -> str | None:
        configured = (self._settings.tesseract_command or "").strip()
        if not configured:
            return None

        expanded = os.path.expandvars(os.path.expanduser(configured))
        candidate = Path(expanded)
        if candidate.is_file():
            return str(candidate)

        return shutil.which(expanded)

    def _temp_root(self) -> str:
        temp_root = self._settings.storage_root / ".tesseract_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        return str(temp_root)

    def _tesseract_version(self) -> str:
        if self._version_cache:
            return self._version_cache

        command = self._resolve_command()
        if command is None:
            self._version_cache = "tesseract"
            return self._version_cache

        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=self._settings.tesseract_timeout_seconds,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            self._version_cache = "tesseract"
            return self._version_cache

        first_line = next(
            (
                line.strip()
                for line in (result.stdout or result.stderr or "").splitlines()
                if line.strip()
            ),
            "tesseract",
        )
        self._version_cache = first_line.replace(" ", "-", 1)
        return self._version_cache

    def _build_text_overlay(self, tsv_path: Path) -> dict[str, Any]:
        if not tsv_path.exists():
            return {"Lines": []}

        grouped_words: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
        with tsv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                text = (row.get("text") or "").strip()
                if not text or int(row.get("level") or 0) != 5:
                    continue

                key = (
                    int(row.get("page_num") or 0),
                    int(row.get("block_num") or 0),
                    int(row.get("par_num") or 0),
                    int(row.get("line_num") or 0),
                )
                grouped_words.setdefault(key, []).append(
                    {
                        "WordText": text,
                        "Left": int(row.get("left") or 0),
                        "Top": int(row.get("top") or 0),
                        "Width": int(row.get("width") or 0),
                        "Height": int(row.get("height") or 0),
                    }
                )

        lines: list[dict[str, Any]] = []
        for words in grouped_words.values():
            ordered_words = sorted(words, key=lambda word: (word["Top"], word["Left"]))
            line_text = " ".join(word["WordText"] for word in ordered_words).strip()
            if not line_text:
                continue
            lines.append({"LineText": line_text, "Words": ordered_words})

        lines.sort(
            key=lambda line: (
                min((word["Top"] for word in line["Words"]), default=0),
                min((word["Left"] for word in line["Words"]), default=0),
            )
        )
        return {"Lines": lines}
