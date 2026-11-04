"""Поправки Максима к поведению бота: правила и примеры «как надо».

Хранятся в JSON-файле (DATA_DIR/overrides.json) и переживают перезапуск.
Попадают в системный промпт выше стилевых подсказок, но ниже правил
безопасности.
"""

from __future__ import annotations

import json
import os
import re
import tempfile

MAX_RULES = 30
MAX_EXAMPLES = 10
MAX_TEXT = 500


# Промпт агента, который ищет поправку в реплике Максима боту
EXTRACT_PROMPT = """Ты помогаешь настраивать бота, который пишет в групповом чате от имени Максима и в его стиле.
Ниже реплика бота (может быть пустой) и сообщение самого Максима, адресованное боту.
Реши, говорит ли Максим, как боту себя вести или как надо было ответить. Обычный разговор, шутка или вопрос по теме — это не поправка.

Верни только JSON одной строкой, без пояснений:
{"kind": "none"} — поправки нет;
{"kind": "rule", "text": "..."} — общее указание боту; сформулируй его коротко, в повелительном наклонении, до 200 символов;
{"kind": "example", "text": "..."} — Максим даёт конкретную формулировку, как надо было ответить вместо реплики бота; верни эту формулировку."""


def parse_correction(raw: str) -> tuple[str, str] | None:
    """Ответ агента → ("rule" | "example", текст) или None."""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    kind, text = data.get("kind"), str(data.get("text") or "").strip()
    if kind not in {"rule", "example"} or not text:
        return None
    return kind, text[:MAX_TEXT]


class Overrides:
    def __init__(self, path: str):
        self.path = path
        self.rules: list[str] = []
        self.examples: list[dict] = []  # {"bot": плохой ответ, "better": как надо}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        self.rules = list(data.get("rules", []))
        self.examples = list(data.get("examples", []))

    def _save(self):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"rules": self.rules, "examples": self.examples}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add_rule(self, text: str) -> int:
        """Добавляет правило, возвращает его номер (с 1)."""
        self.rules.append(text.strip()[:MAX_TEXT])
        del self.rules[:-MAX_RULES]
        self._save()
        return len(self.rules)

    def add_example(self, bot_text: str, better: str) -> int:
        self.examples.append({"bot": bot_text.strip()[:MAX_TEXT], "better": better.strip()[:MAX_TEXT]})
        del self.examples[:-MAX_EXAMPLES]
        self._save()
        return len(self.examples)

    def prompt_section(self) -> str:
        """Блок для системного промпта; пустая строка, если поправок нет."""
        if not self.rules and not self.examples:
            return ""
        parts = [
            "\n\n## Поправки от самого Максима",
            "Максим сам дал эти указания. Они важнее стилевых подсказок и профиля выше, "
            "но не отменяют раздел «Безопасность».",
        ]
        parts += [f"- {r}" for r in self.rules]
        if self.examples:
            parts.append("\nПримеры: так бот ответил неудачно, а так надо было бы.")
            for e in self.examples:
                parts.append(f"- Было: «{e['bot']}»\n  Надо: «{e['better']}»")
        return "\n".join(parts)
