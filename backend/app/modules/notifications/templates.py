"""The wording of every message. Plain text, short, no em dashes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, StrictUndefined


@dataclass(frozen=True)
class Template:
    code: str
    subject: str
    body: str
    optional: bool  # a person may mute it
    sensitive: bool = False  # the body carries a secret and is wiped after sending
    title: str = ""  # how the preferences page names this kind of message

    @property
    def label(self) -> str:
        return self.title or self.subject.split("{{")[0].strip() or self.code.replace("_", " ")


TEMPLATES: dict[str, Template] = {
    t.code: t
    for t in (
        Template(
            "otp_check_in",
            "Your visit code for {{ project }}",
            "Hello {{ name }},\n\n{{ engineer }} from IITPL has arrived at {{ place }} to work on "
            "{{ task }}.\n\nThe code to confirm the arrival is {{ code }}. Share it only with "
            "{{ engineer }}, in person. It works for {{ minutes }} minutes.\n\nIf you did not "
            "expect "
            "a visit, do not share the code and tell your IITPL contact.\n",
            optional=False,
            sensitive=True,
        ),
        Template(
            "otp_handover",
            "Your hand over code for {{ project }}",
            "Hello {{ name }},\n\n{{ engineer }} has finished {{ task }} and asks you to confirm "
            "the "
            "hand over.\n\nThe code is {{ code }}. Give it only after you have seen the work. It "
            "works for {{ minutes }} minutes.\n",
            optional=False,
            sensitive=True,
        ),
        Template(
            "task_assigned",
            "{{ count }} task(s) assigned to you on {{ project }}",
            "Hello {{ name }},\n\nYou have {{ count }} task(s) on {{ project }}. The first one "
            "starts "
            "on {{ first_start }}.\n\nOpen Project One and accept each task before you travel.\n",
            optional=True,
            title="Tasks assigned to me",
        ),
        Template(
            "run_blocked",
            "Blocked: {{ task }} on {{ project }}",
            "Hello {{ name }},\n\n{{ engineer }} cannot continue {{ task }}.\n\nReason: {{ reason "
            "}}\n\n"
            "Please decide what to do next in Project One.\n",
            optional=True,
            title="A task is blocked",
        ),
        Template(
            "task_update",
            "{{ project }}: {{ task }} is now {{ state }}",
            "Hello {{ name }},\n\n{{ task }} on {{ project }} moved to: {{ state }}.\n"
            "{% if note %}\n{{ note }}\n{% endif %}"
            "\nBy {{ actor }} at {{ at }} (IST).\n",
            optional=True,
            title="A field task changes state",
        ),
        Template(
            "verify_requested",
            "Please verify: {{ task }} on {{ project }}",
            "Hello {{ name }},\n\n{{ engineer }} finished {{ task }} and the customer "
            "confirmed the hand over. The configuration check passed{% if not_checked %} with "
            "{{ not_checked }} item(s) left for you to judge{% endif %}.\n\nOpen Project "
            "One to approve it or send it back.\n",
            optional=False,
            title="Work waiting for me to verify",
        ),
        Template(
            "run_returned",
            "Rework needed: {{ task }} on {{ project }}",
            "Hello {{ name }},\n\n{{ task }} was sent back to configuration.\n\n"
            "Why: {{ reason }}\n\nFix it, add any new evidence and send it again.\n",
            optional=False,
            title="My work is sent back",
        ),
        Template(
            "waiver_ack",
            "Please acknowledge an exclusion on {{ project }}",
            "Hello {{ name }},\n\n{{ director }} at IITPL approved leaving this out of the "
            "work on {{ project }}:\n\n{{ what }} ({{ kind }})\nReason: {{ reason }}\n\n"
            "It will be listed as an exclusion on the completion certificate. Please read and "
            "acknowledge it here within {{ days }} days:\n{{ link }}\n",
            optional=False,
            title="Exclusion to acknowledge",
        ),
        Template(
            "handover_done",
            "Hand over confirmed: {{ task }}",
            "Hello {{ name }},\n\n{{ task }} on {{ project }} was handed over and confirmed by the "
            "customer. It is ready for verification.\n",
            optional=True,
            title="A hand over is confirmed",
        ),
        Template(
            "test_message",
            "Test message from Project One",
            "Hello {{ name }},\n\nThis is a test. If it reached this phone or browser, messages "
            "from Project One will reach it too.\n",
            optional=False,
            title="Test message",
        ),
        Template(
            "quote_expiring",
            "Quote {{ quote_ref }} {{ when }}",
            "Hello {{ name }},\n\nVersion {{ version }} of quote {{ quote_ref }} for {{ project }} "
            "{{ when }}. Its prices are valid for {{ days }} days from the quote date.\n\nOpen the "
            "BOQ and choose Re-price: every price is taken again from the price book and the BOQ "
            "goes for pricing approval, then it can be issued as a new version.\n",
            optional=True,
            title="A quote is about to expire",
        ),
        Template(
            "price_drift",
            "Price to check: {{ item }}",
            "Hello {{ name }},\n\nThe price just entered for {{ item }} is {{ change }} percent "
            "{{ direction }} what its price history suggests. Check it before it goes into a "
            "quote.\n\nThis is advice from the learning module, not a rule.\n",
            optional=True,
            title="A price looks unusual",
        ),
    )
}

_env = Environment(autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True)  # nosec B701  # noqa: S701  (plain text mail)


def render(code: str, context: dict[str, Any]) -> tuple[str, str]:
    t = TEMPLATES[code]
    return (
        _env.from_string(t.subject).render(**context).replace("\n", " ")[:200],
        _env.from_string(t.body).render(**context),
    )
