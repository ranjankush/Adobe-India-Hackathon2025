# Round 1A: PDF Outline Extractor

## Overview
This solution extracts a structured outline (title, H1, H2, H3 headings with page numbers) from a PDF file and outputs it as a JSON file for the "Connecting the Dots" Challenge (Round 1A). It uses PyMuPDF for PDF parsing and supports multilingual text with UTF-8 encoding.

## Approach
- **PDF Parsing**: Uses PyMuPDF to extract text blocks, font sizes, flags, and positions.
- **Font Ranking**: Ranks font sizes across up to 50 pages to identify H1, H2, H3.
- **Title Detection**: Identifies the first bold/large text (font size > 14, top of page 1).
- **Heading Detection**: Classifies headings using font size, boldness, position, and hierarchy.
- **Output**: Saves JSON to `output/output.json` with UTF-8 encoding.
- **Multilingual Support**: Uses sentencepiece for non-Latin text (e.g., Japanese, Hindi).
- **Error Handling**: Handles empty PDFs, missing files, malformed content, and complex layouts.
- **Logging**: Logs to `extract_outline.log` and console for debugging.
- **Constraints**: CPU-only, no internet, model size < 200 MB (PyMuPDF ~50 MB).

## Dependencies
- pymupdf==1.26.3
- sentencepiece==0.2.0

## Setup and Execution
1. Place input PDF in the `input/` directory (e.g., `input/sample.pdf`).
2. Build and run the Docker container:
   ```bash
   docker build -t pdf-extractor .
   docker run --rm -v %CD%/input:/app/input -v %CD%/output:/app/output pdf-extractor

## Command for Environment Setup
.venv\Scripts\Activate.ps1                                        
   

## Command for Run
python extract_pdf.py input/Adobe_Hack.pdf output/sample_test.json