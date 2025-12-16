import os
from pathlib import Path

import pytest

from verizon_bill_parser import parser


def test_parse_directory_counts_pdfs():
    parser.set_logger_level("DEBUG")

    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    pdf_files = sorted(data_dir.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("No PDF fixtures found in data/.")

    results = parser.parse_directory(str(data_dir))
    assert len(results) == len(pdf_files)


def test_parse_directory_missing_dir_raises():
    missing_dir = "data1"
    with pytest.raises(Exception) as exc_info:
        parser.parse_directory(missing_dir)
    assert str(exc_info.value) == f"Directory {missing_dir} does not exist"


def test_parse_file_missing_file_raises(tmp_path: Path):
    missing_pdf = tmp_path / "missing.pdf"
    with pytest.raises(Exception) as exc_info:
        parser.parse_file(str(missing_pdf))
    assert str(exc_info.value) == f"File {missing_pdf} does not exist"


def test_parse_file_uses_mypdfutils_and_returns_parsed_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pdf_path = tmp_path / "MyBill_11.15.2024.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    parser.set_logger_level("INFO")

    captured = {}

    class FakeMyPDFUtils:
        def __init__(self, pdf_file_name, log_level):
            captured["pdf_file_name"] = pdf_file_name
            captured["log_level"] = log_level
            self.parsedData = {"fileName": pdf_file_name, "amounts": [{"amount": "$1.00"}]}

    monkeypatch.setattr(parser, "MyPDFUtils", FakeMyPDFUtils)

    result = parser.parse_file(str(pdf_path))
    assert result["fileName"] == str(pdf_path)
    assert result["amounts"][0]["amount"] == "$1.00"
    assert captured["pdf_file_name"] == str(pdf_path)


def test_parse_directory_with_non_pdf_raises(tmp_path: Path):
    (tmp_path / "note.txt").write_text("hello")
    with pytest.raises(Exception) as exc_info:
        parser.parse_directory(str(tmp_path))

    # parse_directory will attempt to parse every file; non-PDF should fail.
    assert "is not a PDF file" in str(exc_info.value)


@pytest.mark.parametrize(
    "pdf_name, expected_bill_date",
    [
        ("MyBill_07.18.2024.pdf", "07/18/2024"),
        ("MyBill_01.18.2025.pdf", "01/18/2025"),
        ("MyBill_10.18.2025.pdf", "10/18/2025"),
    ],
)
def test_parse_file_parses_real_bill_fixtures(pdf_name: str, expected_bill_date: str):
    """Integration test: validates the parser still works on known-good PDFs."""
    parser.set_logger_level("DEBUG")

    repo_root = Path(__file__).resolve().parents[1]
    pdf_path = repo_root / pdf_name
    if not pdf_path.exists():
        pytest.skip(f"Missing fixture: {pdf_name}")

    result = parser.parse_file(str(pdf_path))
    assert result["fileName"] == str(pdf_path)
    assert result.get("billDate") == expected_bill_date

    amounts = result.get("amounts")
    assert isinstance(amounts, list)
    assert len(amounts) > 0

    # Avoid regressing into treating header fragments as charge rows.
    junk_descriptions = {"account-wide", "charges", "&", "credits", "total:"}
    for item in amounts:
        desc = item.get("description")
        if isinstance(desc, str):
            assert desc.strip().lower() not in junk_descriptions

        # Ensure each parsed line item has a corresponding $-amount.
        # (Prevents orphan $ values from shifting alignment and leaving None amounts behind.)
        amount = item.get("amount")
        assert isinstance(amount, str) and amount.startswith("$")

    assert any(
        isinstance(item, dict) and isinstance(item.get("amount"), str) and item["amount"].startswith("$")
        for item in amounts
    )
    