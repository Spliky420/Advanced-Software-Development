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
