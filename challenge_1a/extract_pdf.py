import fitz  # PyMuPDF55
import os
import json
import sys
import logging
import unicodedata
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Sequence

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Optional multilingual normalization (SentencePiece)
try:
    import sentencepiece as spm
    _HAS_SPM = True
except Exception:
    _HAS_SPM = False

# Regex patterns
BULLET_PREFIX_RE = re.compile(r"^[\u2022\-\*\d]+\s*")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"^`{3}")

# Font detection hints
WEIGHT_HINTS = ("bold", "black", "heavy", "semibold", "demi")
ITALIC_HINTS = ("italic", "oblique")

MIN_ALNUM_CHARS = 3  # drop junk like '{', '}' etc.
MAX_HEADING_WORDS_EXTENDED = 25  # allow longer headings

# Optional explicit pattern -> level overrides
HEADING_LEVEL_OVERRIDES = [
    (re.compile(r"^round\s+1a\b", re.I), "H1"),
    (re.compile(r"^round\s+1b\b", re.I), "H1"),
    (re.compile(r"^appendix$", re.I), "H1"),
]


@dataclass
class Heading:
    level: str
    text: str
    page: int


def is_bold_font(font_name: str) -> bool:
    fn = font_name.lower()
    return any(w in fn for w in WEIGHT_HINTS)


def is_italic_font(font_name: str) -> bool:
    fn = font_name.lower()
    return any(w in fn for w in ITALIC_HINTS)


def normalize_basic(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip()


def normalize_sentencepiece(text: str, sp_model_path: Optional[str]) -> str:
    if not (sp_model_path and _HAS_SPM and os.path.exists(sp_model_path)):
        return normalize_basic(text)
    try:
        sp = spm.SentencePieceProcessor(model_file=sp_model_path)
        toks = sp.encode(text, out_type=str)
        return " ".join(toks).strip() or normalize_basic(text)
    except Exception:
        return normalize_basic(text)


def _alnum_count(text: str) -> int:
    return sum(ch.isalnum() for ch in text)


class PDFOutlineExtractor:
    def __init__(
        self,
        pdf_path: str,
        max_pages: int = 50,
        scan_pages_for_stats: int = 5,
        title_scan_pages: int = 3,
        font_size_tolerance: float = 0.75,
        sp_model_path: Optional[str] = None,
        max_heading_words: int = 12,
    ):
        self.pdf_path = pdf_path
        self.max_pages = max_pages
        self.scan_pages_for_stats = scan_pages_for_stats
        self.title_scan_pages = title_scan_pages
        self.font_size_tolerance = font_size_tolerance
        self.sp_model_path = sp_model_path
        self.max_heading_words = max_heading_words

        self.font_ranks: List[float] = []
        self.outline: List[Heading] = []
        self.title: Optional[str] = None

    def _normalize_text(self, text: str) -> str:
        return normalize_sentencepiece(text, self.sp_model_path)

    def _collect_font_ranks(self, doc: fitz.Document) -> None:
        sizes = []
        scan = min(doc.page_count, self.scan_pages_for_stats, self.max_pages)
        for i in range(scan):
            try:
                blocks = doc[i].get_text("dict")["blocks"]
            except Exception:
                continue
            for b in blocks:
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        txt = s["text"].strip()
                        if txt and not is_italic_font(s["font"]):
                            sizes.append(s["size"])
        uniq = sorted(set(sizes), reverse=True)
        collapsed: List[float] = []
        for sz in uniq:
            if not collapsed or abs(sz - collapsed[-1]) > self.font_size_tolerance:
                collapsed.append(sz)
        self.font_ranks = collapsed[:3]
        logger.info(f"Font ranks: {self.font_ranks}")

    def _size_to_level(self, size: float) -> Optional[str]:
        for idx, ranked in enumerate(self.font_ranks):
            if abs(size - ranked) <= self.font_size_tolerance:
                return ("H1", "H2", "H3")[idx]
        return None

    def _should_keep_heading_text(self, text: str, num_lines: int = 1) -> bool:
        if num_lines > 3:
            return False

        if URL_RE.match(text) or CODE_FENCE_RE.match(text):
            return False

        clean = BULLET_PREFIX_RE.sub("", text).strip()

        if _alnum_count(clean) < MIN_ALNUM_CHARS:
            return False

        words = clean.split()
        if len(words) > self.max_heading_words and len(words) > MAX_HEADING_WORDS_EXTENDED:
            return False

        if clean.endswith((".", "?", "!")) and len(words) > 3:
            return False

        return True

    def extract(self) -> Dict[str, Any]:
        if not os.path.exists(self.pdf_path):
            logger.error(f"File not found: {self.pdf_path}")
            return {"title": "Unknown", "outline": []}

        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            logger.error(f"Error opening PDF: {e}")
            return {"title": "Unknown", "outline": []}

        if doc.page_count == 0:
            doc.close()
            return {"title": "Unknown", "outline": []}

        self._collect_font_ranks(doc)
        meta_title = (doc.metadata.get("title") or "").strip() if doc.metadata else ""
        title_size = -1.0

        page_limit = min(doc.page_count, self.max_pages)
        for pno in range(page_limit):
            page = doc[pno]
            pdata = page.get_text("dict")
            for block in pdata["blocks"]:
                lines = block.get("lines", [])
                if not lines:
                    continue

                # Gather all spans in this block
                block_spans = []
                for ln in lines:
                    block_spans.extend(ln.get("spans", []))
                if not block_spans:
                    continue

                raw_text = " ".join(s["text"] for s in block_spans)
                text = self._normalize_text(raw_text)
                if not text:
                    continue

                sizes = [s["size"] for s in block_spans if s["text"].strip()]
                sizes_sorted = sorted(sizes)
                mid = len(sizes_sorted) // 2
                size = sizes_sorted[mid] if sizes_sorted else block_spans[0]["size"]

                font_name = block_spans[0]["font"]

                # Detect heading level
                level = self._size_to_level(size)
                if level is None:
                    if is_bold_font(font_name) and not is_italic_font(font_name):
                        if self.font_ranks and size > self.font_ranks[-1]:
                            level = "H2"
                        else:
                            level = "H3"

                # Pattern overrides
                for rx, forced_level in HEADING_LEVEL_OVERRIDES:
                    if rx.search(text):
                        level = forced_level
                        break

                # Bullet adjustment
                if BULLET_PREFIX_RE.match(text) and len(text.split()) > 1:
                    if level == "H1":
                        level = "H2"
                    elif level == "H2":
                        level = "H3"

                if level and self._should_keep_heading_text(text, num_lines=len(lines)):
                    self.outline.append(Heading(level, text, pno + 1))

                # Title detection
                if pno < self.title_scan_pages and size > title_size:
                    if self._should_keep_heading_text(text, num_lines=len(lines)):
                        self.title = text
                        title_size = size

        doc.close()
        if not self.title:
            self.title = meta_title if meta_title else (self.outline[0].text if self.outline else "Unknown")

        return {"title": self.title, "outline": [h.__dict__ for h in self.outline]}


def process_directory(indir: str, outdir: str) -> int:
    os.makedirs(outdir, exist_ok=True)
    pdfs = [f for f in os.listdir(indir) if f.lower().endswith(".pdf")]
    count = 0
    for fname in pdfs:
        pdf_path = os.path.join(indir, fname)
        base = os.path.splitext(fname)[0] + ".json"
        out_path = os.path.join(outdir, base)
        extractor = PDFOutlineExtractor(pdf_path)
        data = extractor.extract()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        count += 1
        logger.info(f"Wrote {out_path}")
    return count


def _usage():
    print("Usage:")
    print("  python extract_outline.py <pdf_path> [output.json]")
    print("  python extract_outline.py --batch <input_dir> <output_dir>")
    sys.exit(1)


if __name__ == "__main__":
    args: Sequence[str] = sys.argv[1:]
    if not args:
        _usage()

    if args[0] == "--batch":
        if len(args) != 3:
            _usage()
        n = process_directory(args[1], args[2])
        logger.info(f"Processed {n} PDFs.")
        sys.exit(0)

    pdf_path = args[0]
    out_path = args[1] if len(args) > 1 else "output/output.json"
    extractor = PDFOutlineExtractor(pdf_path)
    result = extractor.extract()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))