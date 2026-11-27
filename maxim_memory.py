"""Общая память бота на все группы: бот играет одного человека, и то, что он
узнал или сказал в одном чате, должно быть доступно в другом.

DATA_DIR/memory/ — три слоя, от подробного к общему:

- <chat_id>/days/YYYY-MM-DD.md — заметки за день по сообщениям архива;
- <chat_id>/profile.md — память о чате целиком: люди, темы, шутки, твои позиции
  и обещания; переписывается с каждым новым днём;
- self.md — общая память о себе по всем чатам; переписывается из профилей.

Текст памяти в промпт не передаётся: бот получает пути и читает файлы сам,
когда нужно. Личка в память не попадает.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from typing import Awaitable, Callable

Ask = Callable[[str], Awaitable[str]]

MAX_DAY_CHARS = 60_000

WHO = (
    "Ты — бот, который в групповых чатах играет Максима Дементьева. "
    "В истории твои сообщения подписаны «Бот (ты)». «Максим Дементьев» — настоящий Максим, "
    "его слова о себе — факты о том, кого ты играешь."
)

DAY_PROMPT = WHO + """
Ниже сообщения чата «{title}» за {day}. Запиши заметки для своей памяти:
- кто что важного сказал, о чём спорили, чем кончилось;
- факты о людях: работа, город, интересы, планы, отношения между людьми;
- что ты сам сказал, пообещал, с кем спорил, на чём настаивал;
- шутки и мемы, которые могут повториться.
Коротко, списком, до 2000 знаков, по-русски. Пиши имена так, как они подписаны.
Если за день ничего стоящего не было, верни ровно слово SKIP.

Сообщения:
{messages}"""

PROFILE_PROMPT = WHO + """
Это твоя память о чате «{title}» и заметки за новый день {day}. Перепиши память о чате целиком:
- люди: по короткому абзацу на человека (кто он, что о нём известно, как с ним говорить);
- постоянные темы и шутки чата;
- твои позиции и обещания в этом чате (обещания с датой; выполненные и устаревшие убери).
Важное оставляй, мелочи и устаревшее убирай. До 6000 знаков, по-русски, без вступления.

Текущая память о чате:
{profile}

Заметки за {day}:
{notes}"""

SELF_PROMPT = WHO + """
Ниже твоя память о каждом чате. Перепиши общую память о себе:
- кто ты в этих компаниях и как тебя там воспринимают;
- люди, которые есть в нескольких чатах, и что о них известно;
- твои позиции по темам, которые всплывали;
- что и где ты обещал.
До 4000 знаков, по-русски, без вступления.

Текущая общая память:
{current}

{profiles}"""


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    os.replace(tmp, path)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def format_day(records: list[dict]) -> str:
    """Сообщения дня строками «[чч:мм #id автор ↩id]: текст»; длинный день ужимается."""
    def lines(limit: int) -> list[str]:
        out = []
        for r in records:
            reply = f" ↩{r['reply_to']}" if r.get("reply_to") else ""
            media = f"[{r['media']}] " if r.get("media") else ""
            out.append(f"[{r['date'][11:16]} #{r['id']} {r['from']}{reply}]: {media}{r['text'][:limit]}")
        return out
    for limit in (800, 400, 200, 100):
        text = "\n".join(lines(limit))
        if len(text) <= MAX_DAY_CHARS:
            return text
    return text[-MAX_DAY_CHARS:]


class Memory:
    def __init__(self, data_dir: str, since: str):
        self.root = os.path.abspath(os.path.join(data_dir, "memory"))
        self.since = since
        self.state_path = os.path.join(self.root, "state.json")
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
        except FileNotFoundError:
            state = {}
        self.done: dict[str, str] = state.get("done", {})
        self.titles: dict[str, str] = state.get("titles", {})

    def _save(self) -> None:
        _write(self.state_path, json.dumps(
            {"done": self.done, "titles": self.titles}, ensure_ascii=False, indent=1))

    @property
    def self_path(self) -> str:
        return os.path.join(self.root, "self.md")

    def profile_path(self, chat_id: int) -> str:
        return os.path.join(self.root, str(chat_id), "profile.md")

    def days_dir(self, chat_id: int) -> str:
        return os.path.join(self.root, str(chat_id), "days")

    def chats(self) -> list[int]:
        """Группы, о которых уже есть память."""
        return sorted(int(c) for c in self.titles if os.path.exists(self.profile_path(int(c))))

    def set_title(self, chat_id: int, title: str) -> None:
        if title and self.titles.get(str(chat_id)) != title:
            self.titles[str(chat_id)] = title
            self._save()

    def title(self, chat_id: int) -> str:
        return self.titles.get(str(chat_id), str(chat_id))

    def pending_days(self, chat_id: int, records: list[dict], today: str) -> dict[str, list[dict]]:
        """Дни с сообщениями после последнего обработанного, кроме сегодняшнего (он не закончился)."""
        done = self.done.get(str(chat_id), "")
        by_day: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            day = r["date"][:10]
            if self.since <= day < today and day > done:
                by_day[day].append(r)
        return dict(sorted(by_day.items()))

    async def update_chat(self, chat_id: int, records: list[dict], today: str, ask: Ask) -> int:
        """Заметки за каждый новый день и новый профиль чата. Возвращает, сколько дней обработано."""
        title = self.title(chat_id)
        count = 0
        for day, msgs in self.pending_days(chat_id, records, today).items():
            notes = (await ask(DAY_PROMPT.format(title=title, day=day, messages=format_day(msgs)))).strip()
            if notes and not notes.upper().startswith("SKIP"):
                _write(os.path.join(self.days_dir(chat_id), f"{day}.md"), notes)
                profile = (await ask(PROFILE_PROMPT.format(
                    title=title, day=day, profile=_read(self.profile_path(chat_id)) or "(пусто)", notes=notes,
                ))).strip()
                if profile:
                    _write(self.profile_path(chat_id), profile)
            self.done[str(chat_id)] = day
            self._save()
            count += 1
        return count

    async def update_self(self, ask: Ask) -> None:
        profiles = "\n\n".join(
            f"## Чат «{self.title(c)}»\n{_read(self.profile_path(c))}" for c in self.chats()
        )
        if not profiles:
            return
        text = (await ask(SELF_PROMPT.format(
            current=_read(self.self_path) or "(пусто)", profiles=profiles,
        ))).strip()
        if text:
            _write(self.self_path, text)

    def hint(self, chat_id: int, archive_path: Callable[[int], str]) -> str:
        """Где лежит память и архивы других чатов; пусто, если памяти ещё нет."""
        lines = []
        if os.path.exists(self.self_path):
            lines.append(f"- общая память о себе: {self.self_path}")
        for c in self.chats():
            here = " (этот чат)" if c == chat_id else ""
            lines.append(f"- чат «{self.title(c)}»{here}: {self.profile_path(c)}, по дням — {self.days_dir(c)}/")
            if c != chat_id and os.path.exists(archive_path(c)):
                lines.append(f"  архив сообщений этого чата: {archive_path(c)}")
        if not lines:
            return ""
        return (
            "Ты один человек во всех чатах, и у тебя есть память о них — файлы:\n" + "\n".join(lines) + "\n"
            "Это память, а не задача: загляни (cat, grep), если реплика касается людей, прошлых разговоров, "
            "твоих слов или обещаний. То, что знаешь из другого чата, ты просто помнишь: "
            "не пересказывай, не цитируй и не ссылайся на другой чат и его сообщения. Файлы не меняй."
        )
