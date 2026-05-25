"""Sanitizers that neutralize secrets and instruction-shaped memory text."""

import re

PATTERNS = [
    (
        re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_OPENAI_KEY]",
    ),
    (
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA)[A-Z0-9]{16}\b"),
        "[REDACTED_AWS_ACCESS_KEY]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}", re.IGNORECASE),
        "Bearer [REDACTED_BEARER_TOKEN]",
    ),
    (
        re.compile(
            r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----.*?-----END (?:[A-Z]+ )*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"(\bpassword\b\s*=\s*)[^\s\n]+", re.IGNORECASE),
        r"\1[REDACTED_PASSWORD]",
    ),
    (
        re.compile(r"(\bpassword\b[\"']?\s*:\s*)([\"']?)[^,\n\"']+([\"']?)", re.IGNORECASE),
        r"\1\2[REDACTED_PASSWORD]\3",
    ),
    (
        re.compile(r"((?:Set-)?Cookie:\s*)(.+)", re.IGNORECASE),
        r"\1[REDACTED_COOKIE]",
    ),
    (
        re.compile(r"(\bcookie\s*=\s*)[^\s;]+", re.IGNORECASE),
        r"\1[REDACTED_COOKIE]",
    ),
    (
        re.compile(
            r"(\b(?:api[_-]?key|token|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret|secret|webhook[_-]?url|dsn)\b\s*[:=]\s*)([\"']?)[^\s,\n\"']+([\"']?)",
            re.IGNORECASE,
        ),
        r"\1\2[REDACTED_SECRET]\3",
    ),
    (
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s)]+",
            re.IGNORECASE,
        ),
        "[REDACTED_DSN]",
    ),
]


INSTRUCTION_SHAPED_PATTERNS = [
    re.compile(
        r"\b(?:ignore|override|bypass|disable|forget)\b.{0,80}\b(?:system|developer|instruction|policy|safety|tool|memory)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:as|treat|save|remember)\b.{0,80}\b(?:system|developer|instruction|prompt|policy)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:call|use|invoke|run|execute)\b.{0,80}\b(?:tool|command|shell|bash|python|api)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do not|don't|never)\b.{0,80}\b(?:follow|obey|comply)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(忽略|覆盖|绕过|不要遵守|作为系统|作为开发者|调用工具|执行命令)"),
]


def sanitize_text(text: str) -> str:
    sanitized = text
    for pattern, replacement in PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def looks_instruction_shaped(text: str) -> bool:
    return any(pattern.search(text) for pattern in INSTRUCTION_SHAPED_PATTERNS)


def neutralize_instruction_text(text: str) -> str:
    if looks_instruction_shaped(text):
        return "[REDACTED_INSTRUCTION_LIKE_MEMORY]"
    return text
