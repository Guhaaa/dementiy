"""Поправки владельца к поведению бота: правила и примеры «как надо».

Хранятся в JSON-файле (DATA_DIR/overrides.json) и переживают перезапуск.
Попадают в системный промпт выше стилевых подсказок, но ниже правил
безопасности.
"""

from __future__ import annotations

import json
import os
import tempfile

MAX_RULES = 30
MAX_EXAMPLES = 10
MAX_TEXT = 500


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

    def remove_rule(self, number: int) -> str | None:
        if not 1 <= number <= len(self.rules):
            return None
        removed = self.rules.pop(number - 1)
        self._save()
        return removed

    def remove_example(self, number: int) -> dict | None:
        if not 1 <= number <= len(self.examples):
            return None
        removed = self.examples.pop(number - 1)
        self._save()
        return removed

    def listing(self) -> str:
        lines = ["Правила:"]
        lines += [f"{i}. {r}" for i, r in enumerate(self.rules, 1)] or ["—"]
        lines.append("\nПримеры «как надо»:")
        lines += [
            f"{i}. Было: {e['bot'][:80]}\n   Надо: {e['better']}"
            for i, e in enumerate(self.examples, 1)
        ] or ["—"]
        return "\n".join(lines)

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
