from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.extraction.registry import ExtractionProviderRegistry
from app.services.extraction.providers.tesseract_provider import TesseractExtractionProvider


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / ".test_runtime"


def make_settings(binary_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        tesseract_command=str(binary_path),
        tesseract_language="eng",
        tesseract_page_seg_mode=6,
        tesseract_timeout_seconds=5.0,
    )


def make_runtime_dir() -> Path:
    runtime_dir = RUNTIME_ROOT / f"tesseract-provider-{uuid4().hex}"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def test_registry_includes_tesseract_provider() -> None:
    registry = ExtractionProviderRegistry()

    assert isinstance(registry.get("tesseract"), TesseractExtractionProvider)


def test_tesseract_overlay_groups_words_into_lines() -> None:
    runtime_dir = make_runtime_dir()
    try:
        provider = TesseractExtractionProvider(settings=make_settings(runtime_dir / "tesseract.exe"))
        tsv_path = runtime_dir / "sample.tsv"
        tsv_path.write_text(
            "\n".join(
                [
                    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                    "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t96\tInvoice",
                    "5\t1\t1\t1\t1\t2\t48\t20\t18\t10\t92\t598527",
                    "5\t1\t1\t1\t2\t1\t10\t42\t24\t10\t90\tTotal",
                    "5\t1\t1\t1\t2\t2\t44\t42\t20\t10\t89\t816.42",
                ]
            ),
            encoding="utf-8",
        )

        overlay = provider._build_text_overlay(tsv_path)

        assert [line["LineText"] for line in overlay["Lines"]] == [
            "Invoice 598527",
            "Total 816.42",
        ]
        assert overlay["Lines"][0]["Words"][0]["Left"] == 10
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


def test_tesseract_submit_request_builds_ocr_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_dir = make_runtime_dir()
    fake_binary = runtime_dir / "tesseract.exe"
    fake_binary.write_text("", encoding="utf-8")
    provider = TesseractExtractionProvider(settings=make_settings(fake_binary))

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if "--version" in args:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="tesseract 5.5.2\n", stderr="")

        output_base = Path(args[2])
        output_base.with_suffix(".txt").write_text("Invoice Number 598527", encoding="utf-8")
        output_base.with_suffix(".tsv").write_text(
            "\n".join(
                [
                    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                    "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t96\tInvoice",
                    "5\t1\t1\t1\t1\t2\t50\t20\t35\t10\t93\tNumber",
                    "5\t1\t1\t1\t1\t3\t95\t20\t32\t10\t91\t598527",
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.extraction.providers.tesseract_provider.subprocess.run", fake_run)

    try:
        response = provider._submit_ocr_request(b"fake-image", page_number=1)
        parsed = response["ParsedResults"][0]

        assert parsed["ParsedText"] == "Invoice Number 598527"
        assert parsed["TextOverlay"]["Lines"][0]["LineText"] == "Invoice Number 598527"
        assert provider._analysis_api_version() == "tesseract-5.5.2"
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


def test_tesseract_requires_runnable_binary() -> None:
    runtime_dir = make_runtime_dir()
    try:
        provider = TesseractExtractionProvider(
            settings=Settings(_env_file=None, tesseract_command=str(runtime_dir / "missing.exe"))
        )

        with pytest.raises(RuntimeError, match="no runnable binary was found"):
            provider._ensure_configuration()
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)
