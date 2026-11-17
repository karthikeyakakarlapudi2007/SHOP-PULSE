"""
Document preparation layer for invoice photos.

A separate, self-contained preprocessing stage that sits *in front of* the existing OCR
engine (services.grocery_ocr / services.ocr).  It corrects orientation, perspective, tilt
and lighting, grades image quality, produces a small set of comparable variants and builds
the PDF that is handed to the unchanged invoice extraction pipeline.
"""

from services.document_prep.pipeline import PreparedPage, PrepOptions, prepare_page

__all__ = ["PreparedPage", "PrepOptions", "prepare_page"]
