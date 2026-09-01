from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.templating import Jinja2Templates

from app.humanize import relative_time
from app.scheduling import duration_minutes


def strip_query_param(url: str, key: str) -> str:
    parts = urlsplit(url)
    remaining = [(k, v) for k, v in parse_qsl(parts.query) if k != key]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(remaining), parts.fragment))


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["relative_time"] = relative_time
templates.env.filters["duration_minutes"] = duration_minutes
templates.env.filters["strip_query_param"] = strip_query_param
