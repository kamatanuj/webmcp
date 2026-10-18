#!/usr/bin/env python3
"""Stamp D-Insights logo top-left of every page of the whitepaper PDF."""
import sys, pymupdf as fitz
pdf, png = sys.argv[1], sys.argv[2]
doc = fitz.open(pdf)
for p in doc:
    p.insert_image(fitz.Rect(40, 18, 78, 56), stream=open(png, 'rb').read())
doc.save(pdf + '.tmp', deflate=True); doc.close()
import os; os.replace(pdf + '.tmp', pdf)
print("stamped", pdf)
