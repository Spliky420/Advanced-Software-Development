import re
from datetime import date

DOC_TYPES = (
    "article",
    "guide",
    "report",
    "news",
    "research_note",
    "filing",
    "whitepaper",
    "other",
)

MAX_TITLE_LENGTH = 300
MAX_SOURCE_LENGTH = 200
MIN_BODY_LENGTH = 1

MIN_TERM_LENGTH = 2
MAX_TERM_LENGTH = 60
# Letters, digits, spaces and the punctuation real financial terms use
# (S&P, P/E, dollar-cost, 4.35). Anything else is refused before the MCP
# tool is called -- part of this feature's MCP input boundary.
TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/.\-]*$")


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__("; ".join(self.errors))


def _check_date(value, field_name, errors, required):
    if value is None or value == "":
        if required:
            errors.append(f"{field_name} is required")
        return
    if not isinstance(value, str):
        errors.append(f"{field_name} must be a date string in YYYY-MM-DD format")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_document_payload(data):
    """Validate a create/update payload. PUT replaces the whole document, the
    same convention joshua/backend uses for holdings, so create and update
    share one validator.
    """
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    errors = []

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is required and cannot be empty")
    elif len(title.strip()) > MAX_TITLE_LENGTH:
        errors.append(f"title must be at most {MAX_TITLE_LENGTH} characters")

    source = data.get("source")
    if source is not None and not isinstance(source, str):
        errors.append("source must be a string")
    elif isinstance(source, str) and len(source.strip()) > MAX_SOURCE_LENGTH:
        errors.append(f"source must be at most {MAX_SOURCE_LENGTH} characters")

    doc_type = data.get("doc_type")
    if doc_type not in DOC_TYPES:
        errors.append("doc_type must be one of: " + ", ".join(DOC_TYPES))

    _check_date(data.get("published_on"), "published_on", errors, required=False)

    body_text = data.get("body_text")
    if not isinstance(body_text, str) or len(body_text.strip()) < MIN_BODY_LENGTH:
        errors.append("body_text is required and cannot be empty")

    if errors:
        raise ValidationError(errors)

    clean_source = source.strip() if isinstance(source, str) else None

    return {
        "title": title.strip(),
        "source": clean_source or None,
        "doc_type": doc_type,
        "published_on": data.get("published_on") or None,
        "body_text": body_text.strip(),
    }


def validate_search_payload(data):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    errors = []

    query = data.get("query")
    if not isinstance(query, str) or not query.strip():
        errors.append("query is required and cannot be empty")

    top_k = data.get("top_k", 5)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not (1 <= top_k <= 20):
        errors.append("top_k must be an integer between 1 and 20")

    if errors:
        raise ValidationError(errors)

    return {"query": query.strip(), "top_k": top_k}


def normalise_glossary_term(term):
    """Match the casing Maxwell's glossary stores terms in ('Market Cap',
    'Volatility', 'ETF'): its lookup is an exact, case-sensitive match, and a
    word selected from a document is usually lower-case mid-sentence. Words
    already written in capitals (acronyms like ETF, RBA) are kept as-is.
    """
    def fix(match):
        word = match.group(0)
        return word if len(word) > 1 and word.isupper() else word.capitalize()

    return re.sub(r"[A-Za-z]+", fix, term)


def validate_glossary_payload(data, body_text):
    """Validate a glossary lookup for a term found in one document.

    The term must actually occur in the document's text -- this endpoint is
    "look up a word in this document", not a general glossary proxy.
    """
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    term = data.get("term")
    if not isinstance(term, str) or not term.strip():
        raise ValidationError("term is required and cannot be empty")

    term = " ".join(term.split())
    if not (MIN_TERM_LENGTH <= len(term) <= MAX_TERM_LENGTH):
        raise ValidationError(
            f"term must be between {MIN_TERM_LENGTH} and {MAX_TERM_LENGTH} characters"
        )
    if not TERM_RE.match(term):
        raise ValidationError(
            "term may only contain letters, digits, spaces and & / . -"
        )

    pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, term.split())) + r"(?![A-Za-z0-9])"
    if not re.search(pattern, body_text, re.IGNORECASE):
        raise ValidationError(f"'{term}' does not appear in this document")

    return {"term": term, "lookup_term": normalise_glossary_term(term)}
