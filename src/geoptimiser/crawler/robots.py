"""robots.txt handling following RFC 9309, independent of the Python version.

The standard library's ``urllib.robotparser`` honours ``*`` and ``$`` only in some
Python releases, so the rules are matched here: ``*`` matches any run of
characters, a trailing ``$`` anchors the end, and the longest matching pattern
wins (``Allow`` wins a tie). Matching is iterative (no regular expressions), so a
hostile robots.txt cannot cause catastrophic backtracking.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from geoptimiser.schemas import FetchRecord

_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")
_MAX_RULES = 10_000


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str


def _normalize(value: str) -> str:
    """Uppercase percent-escapes so ``%2f`` and ``%2F`` compare equal."""
    return _PERCENT.sub(lambda m: m.group(0).upper(), value)


def pattern_matches(pattern: str, target: str) -> bool:
    """Match a robots pattern (``*`` wildcard, optional trailing ``$``) as a prefix."""
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    parts = pattern.split("*")
    if not target.startswith(parts[0]):
        return False
    if len(parts) == 1:
        return target == parts[0] if anchored else True
    pos = len(parts[0])
    for part in parts[1:-1]:
        index = target.find(part, pos)
        if index < 0:
            return False
        pos = index + len(part)
    last = parts[-1]
    if anchored:
        return target.endswith(last) and len(target) - len(last) >= pos
    return target.find(last, pos) >= 0


def parse_rules(text: str, agent_token: str) -> tuple[_Rule, ...]:
    """Rules of the group that applies to ``agent_token`` (else ``*``, else none).

    Groups for the same agent are merged. An empty ``Disallow`` is no rule.

    Only the two groups that can be returned (the token's own and ``*``) are kept, and
    each rule line is stored at most once per kept group. Work and memory are therefore
    linear in the (already size-capped) file, however many ``User-agent`` lines it has.
    Before this, every agent named in the file got its own list and every rule was
    appended to every agent of the current block, so N agent lines followed by M rule
    lines cost N x min(M, 10 000) entries (security audit run 1).
    """
    token = agent_token.lower()
    wanted = {token, "*"}
    groups: dict[str, list[_Rule]] = {}
    current: set[str] = set()  # the wanted agents the current block applies to
    in_block = False  # the current block named at least one agent
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        field, sep, value = line.partition(":")
        if not sep:
            continue
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if in_rules:
                current, in_block, in_rules = set(), False, False
            in_block = True
            agent = value.lower()
            if agent in wanted:
                current.add(agent)
                groups.setdefault(agent, [])
        elif field in ("allow", "disallow") and in_block:
            in_rules = True
            if not value or not current:
                continue
            rule = _Rule(field == "allow", _normalize(value))
            for agent in current:
                if len(groups[agent]) < _MAX_RULES:
                    groups[agent].append(rule)
    if token in groups:  # a specific group wins even if it has no rules
        return tuple(groups[token])
    return tuple(groups.get("*", ()))


class RobotsPolicy:
    """Decides whether a user agent may fetch URLs of one origin."""

    def __init__(self, rules: tuple[_Rule, ...] = (), *, allow_all: bool = True):
        self._rules, self._allow_all = rules, allow_all

    def allows(self, url: str) -> bool:
        if not self._allow_all:
            return False
        parts = urlsplit(url)
        target = _normalize(
            (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        )
        best: _Rule | None = None
        for rule in self._rules:
            if not rule.pattern or not pattern_matches(rule.pattern, target):
                continue
            if (
                best is None
                or len(rule.pattern) > len(best.pattern)
                or (len(rule.pattern) == len(best.pattern) and rule.allow)
            ):
                best = rule
        return best is None or best.allow

    @classmethod
    def from_fetch(
        cls, record: FetchRecord, body: bytes | None, user_agent: str
    ) -> "RobotsPolicy":
        """Build a policy from the robots.txt fetch.

        2xx with content: parse it. 2xx but empty or not stored, and any 4xx: no
        restrictions. 5xx, a transport failure, or an unfollowed redirect: the file
        could not be read, so the origin is treated as fully disallowed.
        """
        token = user_agent.split("/", 1)[0]
        if record.outcome == "success":
            if body is None:
                return cls()
            text = body.decode("utf-8", errors="replace")
            return cls(parse_rules(text, token))
        if record.outcome == "http_error" and (record.status_code or 0) < 500:
            return cls()
        return cls(allow_all=False)
