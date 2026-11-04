"""Сообщения бота первым: плавающее расписание и состояние.

Состояние (DATA_DIR/proactive.json) переживает перезапуск: время следующего
поста, группы, где бот видел сообщения, и последние посты (чтобы не повторяться).
"""

from __future__ import annotations

import json
import os
import random
import tempfile
from datetime import datetime, timedelta

MAX_RECENT = 15

PROACTIVE_TASK = """Сейчас ты сам начинаешь разговор в чате, никто тебя не спрашивал.
Найди через web search одну свежую (за последние 7 дней) и действительно интересную находку по темам Максима: LLM и агенты, Claude/Codex/Gemini, инструменты разработчика, C++/Python, компиляторы, Linux и мультимедиа, язык и перевод, наука. Выбирай то, что вызывает мысль или спор, а не пресс-релиз.
Напиши сообщение в чат, как будто Максим сам делится находкой: 1–3 коротких предложения с его реакцией или мыслью, затем ссылка на источник отдельной строкой.
Без заголовков, без markdown, без обращений вроде «Друзья» и без «Смотрите, что нашёл». Ссылка — обычный URL.
Если ничего стоящего не нашлось, верни ровно слово SKIP."""


def next_post_time(
    now: datetime,
    min_hours: float,
    max_hours: float,
    start_hour: int,
    end_hour: int,
    rng: random.Random | None = None,
) -> datetime:
    """Случайное время через min..max часов, внутри активных часов [start, end)."""
    rng = rng or random
    t = now + timedelta(hours=rng.uniform(min_hours, max_hours))
    if start_hour <= t.hour < end_hour:
        return t
    # Вне активных часов — случайный момент в ближайшем следующем окне
    day = t if t.hour < start_hour else t + timedelta(days=1)
    window_start = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return window_start + timedelta(hours=rng.uniform(0, end_hour - start_hour))


def build_task(recent: list[str]) -> str:
    if not recent:
        return PROACTIVE_TASK
    shown = "\n".join(f"- {p[:200]}" for p in recent[-MAX_RECENT:])
    return f"{PROACTIVE_TASK}\n\nНе повторяй темы своих прошлых сообщений:\n{shown}"


def clean_post(raw: str) -> str | None:
    """None, если модель отказалась или в посте нет ссылки."""
    text = raw.strip()
    if not text or text.upper().startswith("SKIP") or "http" not in text:
        return None
    return text


class ProactiveState:
    def __init__(self, path: str):
        self.path = path
        self.next_at: datetime | None = None
        self.chats: set[int] = set()
        self.recent: list[str] = []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        if data.get("next_at"):
            self.next_at = datetime.fromisoformat(data["next_at"])
        self.chats = set(data.get("chats", []))
        self.recent = list(data.get("recent", []))

    def save(self):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "next_at": self.next_at.isoformat() if self.next_at else None,
                "chats": sorted(self.chats),
                "recent": self.recent[-MAX_RECENT:],
            }, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def remember_chat(self, chat_id: int):
        if chat_id not in self.chats:
            self.chats.add(chat_id)
            self.save()

    def add_post(self, text: str):
        self.recent = (self.recent + [text])[-MAX_RECENT:]
        self.save()
