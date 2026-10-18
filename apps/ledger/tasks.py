from . import ocr


def run_receipt_ocr(receipt_id: int) -> None:
    ocr.run_receipt_ocr(receipt_id)


def run_statement_ocr(statement_id: int) -> None:
    ocr.run_statement_ocr(statement_id)
