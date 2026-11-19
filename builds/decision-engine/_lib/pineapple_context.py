"""
pineapple_context - shared read-only context extraction for Pineapple OS.

Used by BOTH the Context Intake Engine (00_INBOX) and the Source Scanner
(external folders). Turns a file into a compact, decision-useful record:
summary + structured facts, never a raw dump.

Truth standard: every extracted claim is tagged FACTS / LIKELY / UNKNOWN.
Pure stdlib core. PDF/DOCX/XLSX use optional libs if present, else graceful
fallback (record marked 'unparsed' with a reason). Images -> metadata only (v1).

NOTHING here ever writes to, moves, renames, or deletes a source file.
"""
from __future__ import annotations

import hashlib
import html.parser
import json
import re
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------ file types
TEXT_EXT = {".txt", ".md", ".markdown", ".log", ".rtf"}
DATA_EXT = {".csv", ".tsv", ".json"}
HTML_EXT = {".html", ".htm"}
DOC_EXT = {".docx"}
SHEET_EXT = {".xlsx"}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SUPPORTED = TEXT_EXT | DATA_EXT | HTML_EXT | DOC_EXT | SHEET_EXT | PDF_EXT | IMAGE_EXT


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: Path, chunk: int = 1 << 20, cap: int = 64 << 20) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            read += len(b)
            if read >= cap:  # hash only first 64MB for huge files (still stable id)
                break
    return h.hexdigest()


# ------------------------------------------------------------------ text extraction
class _HTMLText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _html_to_text(raw: str) -> str:
    p = _HTMLText()
    try:
        p.feed(raw)
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    return "\n".join(p.parts)


def _docx_to_text(path: Path) -> str:
    # stdlib fallback: read word/document.xml, strip tags
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            xml = f.read().decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).strip()


def _xlsx_to_text(path: Path, max_cells: int = 4000) -> str:
    # stdlib fallback: pull shared strings + sheet inline text
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "xl/sharedStrings.xml" in names:
            ss = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            out += re.findall(r"<t[^>]*>([^<]+)</t>", ss)
        for n in names:
            if n.startswith("xl/worksheets/") and n.endswith(".xml"):
                sx = z.read(n).decode("utf-8", "ignore")
                out += re.findall(r"<t[^>]*>([^<]+)</t>", sx)
            if len(out) > max_cells:
                break
    return " ".join(out[:max_cells])


def _pdf_to_text(path: Path) -> tuple[str, str]:
    """Return (text, parser_name). Tries optional libs; '' text if none available."""
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            return ("\n".join((pg.extract_text() or "") for pg in pdf.pages[:30]), "pdfplumber")
    except Exception:
        pass
    for mod in ("pypdf", "PyPDF2"):
        try:
            lib = __import__(mod)
            reader = lib.PdfReader(str(path))
            return ("\n".join((pg.extract_text() or "") for pg in reader.pages[:30]), mod)
        except Exception:
            continue
    return ("", "none")


def extract_text(path: Path) -> tuple[str, str, str]:
    """Return (text, parser_used, status). status in {ok, unparsed, image, empty}."""
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return (path.read_text(encoding="utf-8", errors="ignore"), "text", "ok")
        if ext == ".json":
            raw = path.read_text(encoding="utf-8", errors="ignore")
            try:
                return (json.dumps(json.loads(raw), indent=1)[:200000], "json", "ok")
            except Exception:
                return (raw, "json-raw", "ok")
        if ext in {".csv", ".tsv"}:
            return (path.read_text(encoding="utf-8", errors="ignore")[:200000], "csv", "ok")
        if ext in HTML_EXT:
            return (_html_to_text(path.read_text(encoding="utf-8", errors="ignore")), "html", "ok")
        if ext in DOC_EXT:
            return (_docx_to_text(path), "docx-xml", "ok")
        if ext in SHEET_EXT:
            return (_xlsx_to_text(path), "xlsx-xml", "ok")
        if ext in PDF_EXT:
            txt, parser = _pdf_to_text(path)
            if txt.strip():
                return (txt, parser, "ok")
            return ("", parser, "unparsed")  # scanned/secured pdf, no text layer
        if ext in IMAGE_EXT:
            return ("", "image-meta", "image")
        return ("", "none", "unparsed")
    except Exception as e:
        return ("", "error:%s" % type(e).__name__, "unparsed")


# ------------------------------------------------------------------ extractors
MONEY_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\b\d+(?:\.\d{2})?\s?(?:USD|dollars)\b", re.I)
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})\b", re.I)
PEOPLE_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
VEHICLE_RE = re.compile(r"\b(TW200|motorcycle|moto|dirt\s?bike|ATV|UTV|F-?150|F-?250|truck|trailer|jet\s?ski|car|sedan|SUV|Ford|Honda|Yamaha|Kawasaki|Suzuki)\b", re.I)
PROPERTY_RE = re.compile(r"\b(\d{1,6}\s+[A-Z][a-zA-Z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ct|Court|Ln|Lane|Blvd|Way|Pl|Place))\b")
TASK_RE = re.compile(r"(?:^|\n)\s*(?:TODO|to-?do|need to|must|should|action item|follow[- ]up|remember to)\b[:\-]?\s*(.+)", re.I)
DEADLINE_RE = re.compile(r"\b(?:due|deadline|by|before|expires?|no later than)\b[^.\n]{0,60}", re.I)
RISK_RE = re.compile(r"\b(risk|overdue|late fee|penalty|warning|default|lawsuit|fraud|breach|past due|insufficient|decline[d]?)\b", re.I)
OPP_RE = re.compile(r"\b(grant|opportunity|discount|below market|undervalued|auction|for sale|internship|scholarship|patent|deal|underpriced|estate sale)\b", re.I)
DECISION_RE = re.compile(r"\b(decided|decision|chose|will (?:buy|sell|invest|wait|apply)|going to|plan to|approved|rejected)\b[^.\n]{0,80}", re.I)
BIZ_RE = re.compile(r"\b(business idea|startup|side hustle|monetize|revenue|customers?|MVP|product|service offering|LLC)\b", re.I)
HEDGE_RE = re.compile(r"\b(maybe|probably|likely|might|could|seems|appears|i think|possibly|estimate[d]?|around|approximately|roughly)\b", re.I)

STOP_PEOPLE = {"The", "This", "That", "United States", "New York", "Wells Fargo", "Bank Of",
               "Account Number", "Total", "Date", "Page", "From", "Dear", "Best Regards"}


def _uniq(seq, n=20):
    out = []
    for x in seq:
        x = x.strip()
        if x and x not in out:
            out.append(x)
        if len(out) >= n:
            break
    return out


def extract_entities(text: str) -> dict:
    t = text[:300000]
    people = [p for p in PEOPLE_RE.findall(t) if p not in STOP_PEOPLE and len(p) > 3]
    return {
        "money_amounts": _uniq(MONEY_RE.findall(t), 25),
        "dates": _uniq(DATE_RE.findall(t), 15),
        "deadlines": _uniq(DEADLINE_RE.findall(t), 10),
        "people": _uniq(people, 15),
        "vehicles": _uniq((m if isinstance(m, str) else m[0] for m in VEHICLE_RE.findall(t)), 12),
        "properties": _uniq(PROPERTY_RE.findall(t), 12),
        "tasks": _uniq((m if isinstance(m, str) else m[0] for m in TASK_RE.findall(t)), 15),
        "risks": _uniq((m if isinstance(m, str) else m[0] for m in RISK_RE.findall(t)), 12),
        "opportunities": _uniq((m if isinstance(m, str) else m[0] for m in OPP_RE.findall(t)), 15),
        "decisions": _uniq((m if isinstance(m, str) else m[0] for m in DECISION_RE.findall(t)), 10),
        "business_ideas": _uniq((m if isinstance(m, str) else m[0] for m in BIZ_RE.findall(t)), 8),
    }


def summarize(text: str, max_sentences: int = 3) -> str:
    """Cheap extractive summary: rank sentences by keyword salience. No LLM."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= max_sentences:
        return text[:600]
    salient = ("$", "buy", "sell", "due", "risk", "deal", "grant", "decision", "ROI",
               "price", "loan", "auction", "patent", "opportunity", "total", "balance")
    scored = []
    for i, s in enumerate(sentences[:200]):
        sc = sum(s.lower().count(k.lower()) for k in salient)
        sc += 1.0 / (i + 1)  # early sentences matter
        scored.append((sc, i, s))
    top = sorted(scored, key=lambda x: x[0], reverse=True)[:max_sentences]
    top.sort(key=lambda x: x[1])
    return " ".join(s for _, _, s in top)[:600]


def truth_classify(text: str, entities: dict) -> dict:
    """Sort signal into FACTS / LIKELY / UNKNOWN per the Pineapple truth standard."""
    facts, likely, unknown = [], [], []
    for amt in entities.get("money_amounts", [])[:8]:
        facts.append("Money figure present: %s" % amt)
    for d in entities.get("decisions", [])[:5]:
        (likely if HEDGE_RE.search(d) else facts).append("Decision: %s" % d.strip())
    for q in re.findall(r"[^.\n]*\?", text[:5000])[:5]:
        unknown.append("Open question: %s" % q.strip()[:120])
    for sent in re.split(r"(?<=[.!?])\s+", text[:8000]):
        if HEDGE_RE.search(sent) and len(sent) < 160:
            likely.append(sent.strip())
            if len(likely) >= 6:
                break
    return {"FACTS": _uniq(facts, 10), "LIKELY": _uniq(likely, 8), "UNKNOWN": _uniq(unknown, 6)}


# ------------------------------------------------------------------ record
@dataclass
class ContextRecord:
    source_path: str
    source_name: str = ""
    filename: str = ""
    extension: str = ""
    size_bytes: int = 0
    date_added: str = field(default_factory=utcnow)
    date_modified: str = ""
    date_created: str = ""
    sha256: str = ""
    parser_used: str = ""
    status: str = ""          # ok / unparsed / image / empty / skipped
    reason: str = ""
    title: str = ""
    summary: str = ""
    confidence: float = 0.0
    tags: list = field(default_factory=list)
    truth: dict = field(default_factory=dict)
    entities: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _tags_from(ext: str, entities: dict) -> list:
    tags = []
    if entities.get("money_amounts"):
        tags.append("money")
    if entities.get("vehicles"):
        tags.append("vehicle")
    if entities.get("properties"):
        tags.append("property")
    if entities.get("opportunities"):
        tags.append("opportunity")
    if entities.get("risks"):
        tags.append("risk")
    if entities.get("tasks"):
        tags.append("task")
    if entities.get("business_ideas"):
        tags.append("business")
    if ext in IMAGE_EXT:
        tags.append("image")
    return tags or ["misc"]


def build_record(path: Path, source_name: str = "") -> ContextRecord:
    """Read-only: builds a context record. Never writes/moves/edits the source."""
    p = Path(path)
    st = p.stat()
    rec = ContextRecord(
        source_path=str(p), source_name=source_name, filename=p.name,
        extension=p.suffix.lower(), size_bytes=st.st_size,
        date_modified=datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        date_created=datetime.fromtimestamp(getattr(st, "st_ctime", st.st_mtime), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    try:
        rec.sha256 = file_sha256(p)
    except Exception as e:
        rec.status, rec.reason = "skipped", "hash_failed:%s" % type(e).__name__
        return rec

    text, parser, status = extract_text(p)
    rec.parser_used, rec.status = parser, status
    rec.title = p.stem.replace("_", " ").replace("-", " ").strip()[:120]

    if status == "image":
        rec.reason = "image: metadata only (OCR not enabled in v1)"
        rec.tags = ["image"]
        rec.confidence = 0.2
        return rec
    if status != "ok" or not text.strip():
        rec.status = "unparsed" if status != "ok" else "empty"
        rec.reason = rec.reason or ("no text layer / unsupported (%s)" % parser)
        rec.confidence = 0.0
        return rec

    ents = extract_entities(text)
    rec.entities = ents
    rec.summary = summarize(text)
    rec.truth = truth_classify(text, ents)
    rec.tags = _tags_from(rec.extension, ents)
    signal = sum(len(v) for v in ents.values())
    rec.confidence = round(min(0.95, 0.3 + signal * 0.03), 2)
    return rec


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        r = build_record(Path(sys.argv[1]), "cli")
        print(json.dumps(r.to_dict(), indent=2)[:2500])
    else:
        print("usage: python pineapple_context.py <file>")
