"""The one credential detector the platform scrubs text with, before a model or a reader sees it.

The harness recognises vendor key shapes. A credential pasted into a chat just as
often travels inside an address, a query string, a form body or a header, or
carries a prefix of a provider the harness does not list, so these patterns are
added to its own and every caller uses this detector rather than the harness's.
"""

from pydantic_ai_harness.guardrails.detectors import secret_data

PLATFORM_SECRET_PATTERNS: dict[str, str] = {
    "url_credentials": r"(?<=://)[^\s:/?#@\[\]]+:[^\s/?#@\[\]]+(?=@)",
    "query_secret": (
        r"(?i)(?<![A-Za-z0-9_-])(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token"
        r"|id[_-]?token|auth[_-]?token|token|client[_-]?secret|secret|password|passwd)"
        r"=(?!\[redacted:)[^&\s#\"'<>]+"
    ),
    "basic_authorization": r"(?i)\bauthorization\s*[:=]\s*basic\s+[A-Za-z0-9+/]+={0,2}",
    "bearer_token": (
        r"(?i)\bbearer\s+(?=[A-Za-z0-9._~+/-]*\d)(?=[A-Za-z0-9._~+/-]*[A-Za-z])"
        r"[A-Za-z0-9._~+/-]{16,}=*"
    ),
    "huggingface_token": r"\bhf_[A-Za-z0-9]{30,}",
    "groq_key": r"\bgsk_[A-Za-z0-9]{40,}",
    "xai_key": r"\bxai-[A-Za-z0-9]{40,}",
    "gitlab_token": r"\bglpat-[A-Za-z0-9_-]{20,}",
    "sendgrid_key": r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    "npm_token": r"\bnpm_[A-Za-z0-9]{36}\b",
    "telegram_bot_token": r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
}

redact_secrets = secret_data(extra=PLATFORM_SECRET_PATTERNS)
