"""Cleaning for library documents. Pure functions, no database, deterministic.

Every change to what these functions produce bumps `CLEANING_VERSION`, so a dataset version
always says which cleaning made it (RULES.md, data rules).

What is cleaned:
- text: Unicode NFKC, curly quotes, bullets, non-breaking and repeated spaces;
- page-header noise: a heading printed over a line on a page break ("FHoigrhti nPerito ...")
  is taken back out when the heading can be found inside the text as a subsequence;
- domain spelling: a small dictionary of words seen misspelt in real BOQs;
- component names: a canonical, comparable form (`canonical_name`) and a short `name_key`;
- labels: each BOQ line gets a gap type (the same keys as the BOQ templates) and a line role
  (product, setup, support, service), with the rule that matched, so labels are explainable.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CLEANING_VERSION = "2"

# Interleaved text has capital letters inside words: "FHoigrhti". Real product names rarely do
# this more than once (for example "FortiGate", "SonicWall"), so two hits mark a line as garbled.
_INNER_CAP = re.compile(r"[a-z][A-Z][a-z]|[A-Z]{2}[a-z]")

_SPELLING = {
    "phoneix": "phoenix",
    "quarentine": "quarantine",
    "quarantien": "quarantine",
    "licence": "licence",
    "license": "licence",
    "licenses": "licences",
    "liscense": "licence",
    "anti virus": "antivirus",
    "anti-virus": "antivirus",
    "end point": "endpoint",
    "set up": "setup",
    "set-up": "setup",
    "fire wall": "firewall",
    "configration": "configuration",
    "configuraton": "configuration",
    "managment": "management",
    "mangement": "management",
    "sanitisation": "sanitization",
    "malious": "malicious",
    "dorment": "dormant",
    "monthy": "monthly",
    "santization": "sanitization",
}
_SPELLING_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_SPELLING, key=len, reverse=True)) + r")\b",
    re.I,
)

_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "",
        "\u25cf": "",
        "\u25aa": "",
        "\uf0b7": "",
        "\u00a0": " ",
    }
)


def normalise_text(s: str | None) -> str:
    """Unicode NFKC, plain quotes and hyphens, no bullets, single spaces, trimmed."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES)
    s = re.sub(r"[ \t]+", " ", s)
    return "\n".join(part.strip() for part in s.split("\n")).strip()


def fix_spelling(s: str) -> str:
    """Correct the domain words that real BOQs misspell, keeping the original capitalisation
    style of the first letter."""

    def repl(m: re.Match[str]) -> str:
        word = m.group(0)
        fixed = _SPELLING[word.lower()]
        return fixed[:1].upper() + fixed[1:] if word[:1].isupper() else fixed

    return _SPELLING_RE.sub(repl, s)


def looks_garbled(s: str) -> bool:
    return len(_INNER_CAP.findall(s)) >= 2


def _remove_subsequence(text: str, noise: str) -> str | None:
    """Remove `noise` from `text` as an in-order subsequence (left to right, greedy). Returns
    None when `noise` is not a subsequence of `text`."""
    kept: list[str] = []
    j = 0
    for ch in text:
        if j < len(noise) and ch == noise[j]:
            j += 1
        else:
            kept.append(ch)
    return "".join(kept) if j == len(noise) else None


def repair_interleaved(text: str, headings: list[str]) -> tuple[str, str | None]:
    """Try to take a page heading back out of a garbled line.

    The garbled part is the start of the line: the heading's characters were printed in between
    the line's characters. For each heading, and each prefix length, remove the heading as a
    subsequence; keep the first result that is no longer garbled. Returns (text, heading used)
    or (text, None) when nothing helped."""
    if not looks_garbled(text):
        return text, None
    for heading in sorted({h for h in headings if h}, key=len, reverse=True):
        for cut in range(len(heading), min(len(text), len(heading) * 3) + 1):
            head = _remove_subsequence(text[:cut], heading)
            if head is None:
                continue
            candidate = re.sub(r"\s+", " ", head + text[cut:]).strip()
            if not looks_garbled(candidate):
                return candidate, heading
    return text, None


def canonical_name(s: str) -> str:
    """A comparable form: spelling fixed, lower case, punctuation folded, single spaces."""
    s = fix_spelling(normalise_text(s)).lower()
    s = re.sub(r"[^a-z0-9+.%/ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_key(s: str, words: int = 6) -> str:
    """A short key for grouping near-identical names: the first meaningful words, sorted."""
    stop = {"the", "and", "with", "for", "of", "per", "a", "an", "to", "in", "on", "inclusive"}
    toks = [t for t in canonical_name(s).replace("/", " ").split() if t not in stop]
    return " ".join(sorted(toks[:words]))


# ------------------------------------------------------------------ labels


@dataclass(frozen=True)
class Label:
    gap_type: str
    line_role: str
    rule: str
    confidence: float


# Order matters: the first rule that matches wins. Each rule is (gap type, words that must
# appear in the canonical text, any one of). Keys match `boq/templates.py`.
_GAP_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("conflicting_av", ("sanitization", "sanitize", "quarantine", "remove duplicate antivirus")),
    ("no_dlp", ("dlp", "data loss prevention", "data leak")),
    ("no_disaster_recovery", ("odr", "disaster recovery", " dr ", "phoenix", "replication")),
    ("server_not_hardened", ("hardening", "harden", "cis benchmark")),
    ("no_second_dc", ("ad/dc", "ad dc", "domain controller", "active directory", "additional dc")),
    ("backup_at_risk", ("nas", "backup", "synology", "qnap", "storage")),
    ("unmanaged_switch", ("switch", "catalyst", "vlan")),
    (
        "firewall_underconfigured",
        ("firewall", "utm", "fortigate", "sophos xgs", "sonicwall", "vpn", "ngfw"),
    ),
    ("server_xdr", ("server xdr", "xdr for server", "server protection")),
    (
        "no_unified_eps",
        ("xdr", "edr", "eps", "endpoint security", "endpoint protection", "antivirus"),
    ),
    ("underspec_hardware", (" ram", "ram ", "memory", "ddr4", "ddr5", "ssd upgrade")),
    ("outdated_licence", ("office", "microsoft 365", "m365", "ms office")),
    ("os_end_of_support", ("windows 11", "os upgrade", "operating system")),
]

# An explicit "support" wins; then setup words; then softer support words ("management",
# "one year"), because a line such as "implementation + one year management" is mainly a setup.
_ROLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("support", ("support", "amc", "annual maintenance")),
    (
        "setup",
        (
            "setup",
            "installation",
            "implementation",
            "configuration",
            "reconfiguration",
            "migration",
        ),
    ),
    ("support", ("management", "managed service", "one year")),
    ("service", ("sanitization", "hardening", "audit", "assessment", "training")),
]


def label_line(component: str, description: str = "", inclusions: list[str] | None = None) -> Label:
    """Gap type and line role for a BOQ line, with the rule that decided it.

    The component title decides first; the description and inclusions are only used when the
    title alone matches nothing (they often mention other products)."""
    title = f" {canonical_name(component)} "
    rest = f" {canonical_name(description + ' ' + ' '.join(inclusions or []))} "
    gap, rule, conf = "other", "no rule matched", 0.3
    for text, base in ((title, 0.95), (rest, 0.7)):
        hit = next(((g, w) for g, words in _GAP_RULES for w in words if w in text), None)
        if hit:
            gap, rule, conf = (
                hit[0],
                f"'{hit[1].strip()}' in {'title' if base > 0.9 else 'details'}",
                base,
            )
            break
    role = "product"
    for r, words in _ROLE_RULES:
        if any(w in title for w in words):
            role = r
            break
    return Label(gap, role, rule, conf)


def label_lines(lines: list[tuple[str, str, str, list[str]]]) -> list[Label]:
    """Label a whole document. Each item is (section, component, description, inclusions).

    A setup or support line that names no product ("One time setup and configuration charges")
    belongs to the product line above it in the same section, as in every ITCraft quotation."""
    out: list[Label] = []
    for i, (section, component, description, inclusions) in enumerate(lines):
        lab = label_line(component, description, inclusions)
        if lab.gap_type == "other" and lab.line_role in ("setup", "support"):
            for j in range(i - 1, -1, -1):
                if lines[j][0] != section:
                    break
                if out[j].gap_type != "other":
                    lab = Label(out[j].gap_type, lab.line_role, f"follows line {j + 1}", 0.75)
                    break
        out.append(lab)
    return out


TAXONOMY = [g for g, _ in _GAP_RULES] + ["other"]
LINE_ROLES = ["product", "setup", "support", "service"]
