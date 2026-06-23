"""Pure helpers for normalising GitHub upstream source locations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .model import Err, Ok, Result

PUBLIC_API_URL = "https://api.github.com"
PUBLIC_WEB_URL = "https://github.com"


@dataclass(frozen=True, slots=True)
class GitHubSourceLocation:
    repo: str
    api_url: str
    web_url: str
    cache_key: str


@dataclass(frozen=True, slots=True)
class GitHubUrlParts:
    """A GitHub URL decomposed into the fields an upstream entry needs.

    ``ref``/``path``/``is_file`` are ``None`` for a bare repo-root URL; ``api_url`` is ``None``
    for public ``github.com``.
    """

    repo: str
    web_url: str
    ref: Optional[str] = None
    path: Optional[str] = None
    is_file: Optional[bool] = None
    api_url: Optional[str] = None


@dataclass(frozen=True, slots=True)
class _ParsedRepo:
    repo: str
    api_url: Optional[str] = None
    web_url: Optional[str] = None


def default_api_url() -> str:
    return _strip_trailing_slash(os.environ.get("GITHUB_API_URL", PUBLIC_API_URL))


def github_source_errors(source) -> Tuple[str, ...]:
    errors = []
    repo_result = _parse_repo(getattr(source, "repo", None))
    if isinstance(repo_result, Err):
        errors.append(f"repo {repo_result.reason}")

    api_url = getattr(source, "api_url", None)
    if api_url is not None:
        api_result = _normalise_url(api_url)
        if isinstance(api_result, Err):
            errors.append(f"api_url {api_result.reason}")

    web_url = getattr(source, "web_url", None)
    if web_url is not None:
        web_result = _normalise_url(web_url)
        if isinstance(web_result, Err):
            errors.append(f"web_url {web_result.reason}")

    return tuple(errors)


def resolve_github_location(source) -> Result:
    errors = github_source_errors(source)
    if errors:
        return Err("; ".join(f"source.{error}" for error in errors), code=2)

    repo = _parse_repo(source.repo)
    assert isinstance(repo, Ok)
    parsed_repo = repo.value

    source_api_url = getattr(source, "api_url", None)
    if source_api_url is not None:
        api_result = _normalise_url(source_api_url)
        assert isinstance(api_result, Ok)
        api_url = api_result.value
    elif parsed_repo.api_url is not None:
        api_url = parsed_repo.api_url
    else:
        api_url = default_api_url()

    source_web_url = getattr(source, "web_url", None)
    if source_web_url is not None:
        web_result = _normalise_url(source_web_url)
        assert isinstance(web_result, Ok)
        web_url = web_result.value
    elif parsed_repo.web_url is not None:
        web_url = parsed_repo.web_url
    else:
        web_url = _derive_web_url(api_url, parsed_repo.repo)

    return Ok(
        GitHubSourceLocation(
            repo=parsed_repo.repo,
            api_url=api_url,
            web_url=web_url,
            cache_key=f"{_cache_host(api_url)}/{parsed_repo.repo}",
        )
    )


def _parse_repo(value) -> Result:
    if not isinstance(value, str) or not value:
        return Err("must be 'owner/name' or an HTTPS GitHub URL")

    if "://" in value:
        return _parse_repo_url(value)

    owner, sep, name = value.partition("/")
    if not owner or not sep or not name or "/" in name:
        return Err("must be 'owner/name' or an HTTPS GitHub URL")
    return Ok(_ParsedRepo(repo=f"{owner}/{name}"))


def _parse_repo_url(value: str) -> Result:
    parsed = urlsplit(value)
    error = _url_error(parsed, allow_http=False)
    if error is not None:
        return Err(error)

    raw_parts = [part for part in parsed.path.split("/") if part]
    if len(raw_parts) != 2:
        return Err("must identify exactly an owner and repository")

    owner, name = raw_parts
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return Err("must identify exactly an owner and repository")

    repo = f"{owner}/{name}"
    web_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{repo}", "", ""))
    api_url = PUBLIC_API_URL if parsed.netloc == "github.com" else _strip_trailing_slash(
        urlunsplit((parsed.scheme, parsed.netloc, "/api/v3", "", ""))
    )
    return Ok(_ParsedRepo(repo=repo, api_url=api_url, web_url=web_url))


def parse_github_url(value) -> Result:
    """Decompose a GitHub URL into :class:`GitHubUrlParts`.

    Accepts a bare repo URL *and* the browser deep-link forms ``/tree/<ref>/<path>`` (a
    directory) and ``/blob/<ref>/<path>`` (a file) — the URLs you copy while viewing an artifact.
    Query strings and fragments (``?plain=1``, ``#L40``) are stripped, not rejected. The ref is
    the first segment after ``tree``/``blob``; a ref that itself contains slashes cannot be told
    from the path here and must be supplied explicitly by the caller.

    This is deliberately separate from :func:`_parse_repo`, which keeps its strict "exactly
    owner/name" contract for the persisted ``source.repo`` field.
    """
    if not isinstance(value, str) or not value:
        return Err("must be an HTTPS GitHub URL", code=2)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return Err("must be an absolute HTTPS URL", code=2)
    if parsed.username or parsed.password:
        return Err("must not include credentials", code=2)

    segments = [part for part in parsed.path.split("/") if part]
    if len(segments) < 2:
        return Err("must identify at least an owner and repository", code=2)

    owner, name = segments[0], segments[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return Err("must identify exactly an owner and repository", code=2)

    repo = f"{owner}/{name}"
    web_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{repo}", "", ""))
    api_url = (
        None
        if parsed.netloc == "github.com"
        else _strip_trailing_slash(urlunsplit((parsed.scheme, parsed.netloc, "/api/v3", "", "")))
    )

    rest = segments[2:]
    ref: Optional[str] = None
    path: Optional[str] = None
    is_file: Optional[bool] = None
    if rest:
        marker = rest[0]
        if marker not in ("tree", "blob"):
            return Err(
                "URL must be a repository root or a '/tree/<ref>/<path>' "
                "or '/blob/<ref>/<path>' link",
                code=2,
            )
        if len(rest) < 2:
            return Err(f"'{marker}' URL must include a ref segment", code=2)
        is_file = marker == "blob"
        ref = rest[1]
        path_parts = rest[2:]
        path = "/".join(path_parts) if path_parts else None

    return Ok(
        GitHubUrlParts(
            repo=repo,
            web_url=web_url,
            ref=ref,
            path=path,
            is_file=is_file,
            api_url=api_url,
        )
    )


def _normalise_url(value) -> Result:
    if not isinstance(value, str) or not value:
        return Err("must be an absolute HTTP(S) URL")
    parsed = urlsplit(value)
    error = _url_error(parsed, allow_http=True)
    if error is not None:
        return Err(error)
    return Ok(_strip_trailing_slash(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))))


def _url_error(parsed: SplitResult, *, allow_http: bool) -> Optional[str]:
    schemes = ("http", "https") if allow_http else ("https",)
    scheme_label = "HTTP(S)" if allow_http else "HTTPS"
    if parsed.scheme not in schemes or not parsed.netloc:
        return f"must be an absolute {scheme_label} URL"
    if parsed.username or parsed.password:
        return "must not include credentials"
    if parsed.query or parsed.fragment:
        return "must not include query strings or fragments"
    return None


def _derive_web_url(api_url: str, repo: str) -> str:
    if api_url == PUBLIC_API_URL:
        return f"{PUBLIC_WEB_URL}/{repo}"
    parsed = urlsplit(api_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v3"):
        path = path[: -len("/api/v3")]
    else:
        path = ""
    return _strip_trailing_slash(urlunsplit((parsed.scheme, parsed.netloc, f"{path}/{repo}", "", "")))


def _cache_host(api_url: str) -> str:
    if api_url == PUBLIC_API_URL:
        return "github.com"
    parsed = urlsplit(api_url)
    path = parsed.path.rstrip("/")
    if path == "/api/v3":
        path = ""
    return _strip_trailing_slash(f"{parsed.netloc}{path}")


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")
