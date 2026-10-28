"""The log filter keeps guest tags and receipts out of log output (Guest-Identity-and-Visits 6)."""

import logging

from app.main import RedactIdentifiers

TAG = "1C669-J0TDY"
RECEIPT = "abr1_" + "A" * 43


def _record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, args or None, None)


def test_tag_and_receipt_are_redacted_from_the_message() -> None:
    record = _record("review by %s with %s", TAG, RECEIPT)
    assert RedactIdentifiers().filter(record) is True
    text = record.getMessage()
    assert TAG not in text and RECEIPT not in text
    assert "[guest-tag]" in text and "[receipt]" in text


def test_clean_messages_are_left_alone() -> None:
    record = _record("visit counted")
    assert RedactIdentifiers().filter(record) is True
    assert record.getMessage() == "visit counted"
