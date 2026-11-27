"""Архив сообщений чата: DATA_DIR/chats/<chat_id>/archive.jsonl, по сообщению в строке.

Это рабочий каталог сессии Codex этого чата, поэтому Codex ищет по архиву
grep'ом: не было ли уже этой новости, и даёт ссылку на найденное сообщение.
Бот дописывает каждое сообщение группы; старую историю добавляет импорт
выгрузки Telegram (JSON из Telegram Desktop):

    python3 maxim_archive.py import result.json [DATA_DIR]

uid авторов в старые записи (из выгрузки по id сообщения и из лога бота по имени):

    python3 maxim_archive.py fill-uids DATA_DIR BOT_ID result.json|- data/logs/bot.log...
"""

from __future__ import annotations

import json
import os
import re
import sys

ARCHIVE_NAME = "archive.jsonl"
META_NAME = "meta.json"
MAX_TEXT = 4000


def chat_dir(data_dir: str, chat_id: int) -> str:
    return os.path.join(data_dir, "chats", str(chat_id))


def message_link_base(chat_id: int, username: str | None) -> str:
    """Начало ссылки на сообщение: дальше /<id>."""
    if username:
        return f"https://t.me/{username}"
    return f"https://t.me/c/{str(chat_id).removeprefix('-100')}"


# media_type выгрузки → как называем вложение
_EXPORT_MEDIA = {
    "video_file": "видео", "animation": "гифка", "sticker": "стикер", "voice_message": "голосовое",
    "video_message": "кружок", "audio_file": "аудио",
}


def export_media(m: dict) -> str:
    if "photo" in m:
        return "фото"
    if m.get("media_type"):
        return _EXPORT_MEDIA.get(m["media_type"], "файл")
    return "файл" if "file" in m else ""


def record(msg_id: int, date: str, sender: str, text: str,
           links: list[str] | None = None, reply_to: int | None = None, media: str = "",
           uid: int | None = None) -> dict:
    """media — вложение, которого в архиве нет (часто новость приходит скриншотом).
    uid — Telegram id автора: имя в подписи меняется, id нет."""
    rec = {"id": msg_id, "date": date, "from": sender, "text": text[:MAX_TEXT]}
    if uid:
        rec["uid"] = uid
    if media:
        rec["media"] = media
    if links:
        rec["links"] = links
    if reply_to:
        rec["reply_to"] = reply_to
    return rec


def export_uid(m: dict) -> int | None:
    """from_id выгрузки: «user123» → 123; каналы и пустое — None."""
    raw = m.get("from_id") or ""
    return int(raw[4:]) if raw.startswith("user") and raw[4:].isdigit() else None


def flatten_export_text(text) -> tuple[str, list[str]]:
    """Поле text выгрузки: строка или список кусков с разметкой → (текст, ссылки)."""
    if isinstance(text, str):
        return text, []
    parts, links = [], []
    for piece in text:
        if isinstance(piece, str):
            parts.append(piece)
            continue
        parts.append(piece.get("text", ""))
        if piece.get("type") == "text_link" and piece.get("href"):
            links.append(piece["href"])
    return "".join(parts), links


class ChatArchive:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._usernames: dict[int, str | None] = {}

    def path(self, chat_id: int) -> str:
        return os.path.join(chat_dir(self.data_dir, chat_id), ARCHIVE_NAME)

    def append(self, chat_id: int, rec: dict) -> None:
        os.makedirs(chat_dir(self.data_dir, chat_id), exist_ok=True)
        with open(self.path(chat_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def ids(self, chat_id: int) -> set[int]:
        return {m["id"] for m in self._read(chat_id)}

    def _read(self, chat_id: int) -> list[dict]:
        try:
            with open(self.path(chat_id), encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def records(self, chat_id: int) -> list[dict]:
        return self._read(chat_id)

    def recent_ids(self, chat_id: int, since: str) -> list[int]:
        """id сообщений с датой не раньше since (ISO в UTC, как в архиве)."""
        return [m["id"] for m in self._read(chat_id) if m["date"] >= since]

    def remove(self, chat_id: int, ids: set[int]) -> int:
        """Удаляет сообщения из архива (их удалили в чате). Возвращает, сколько удалено."""
        records = self._read(chat_id)
        kept = [m for m in records if m["id"] not in ids]
        if len(kept) == len(records):
            return 0
        tmp = self.path(chat_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(m, ensure_ascii=False) + "\n" for m in kept)
        os.replace(tmp, self.path(chat_id))
        return len(records) - len(kept)

    def fill_uids(self, chat_id: int, by_id: dict[int, int], by_name: dict[str, int]) -> int:
        """Дописывает uid в старые записи: по id сообщения, иначе по имени автора."""
        records = self._read(chat_id)
        filled = 0
        for m in records:
            if m.get("uid"):
                continue
            if uid := by_id.get(m["id"]) or by_name.get(m["from"]):
                m["uid"] = uid
                filled += 1
        if filled:
            tmp = self.path(chat_id) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(m, ensure_ascii=False) + "\n" for m in records)
            os.replace(tmp, self.path(chat_id))
        return filled

    def remember_username(self, chat_id: int, username: str | None) -> None:
        """username публичной группы нужен для ссылок; храним в meta.json."""
        if self._usernames.get(chat_id, "") == username:
            return
        self._usernames[chat_id] = username
        os.makedirs(chat_dir(self.data_dir, chat_id), exist_ok=True)
        with open(os.path.join(chat_dir(self.data_dir, chat_id), META_NAME), "w", encoding="utf-8") as f:
            json.dump({"username": username}, f)

    def link_base(self, chat_id: int) -> str:
        if chat_id not in self._usernames:
            try:
                with open(os.path.join(chat_dir(self.data_dir, chat_id), META_NAME), encoding="utf-8") as f:
                    self._usernames[chat_id] = json.load(f).get("username")
            except FileNotFoundError:
                self._usernames[chat_id] = None
        return message_link_base(chat_id, self._usernames[chat_id])

    def import_export(self, export: dict) -> tuple[int, int]:
        """Добавляет сообщения выгрузки, которых ещё нет. Возвращает (chat_id, сколько добавлено)."""
        chat_id = -1000000000000 - int(export["id"])  # -100<id> для групп
        if export.get("type") in {"public_supergroup", "public_channel"} and export.get("username"):
            self.remember_username(chat_id, export["username"])
        known = self.ids(chat_id)
        added = 0
        for m in sorted(export.get("messages", []), key=lambda m: m["id"]):
            if m.get("type") != "message" or m["id"] in known:
                continue
            text, links = flatten_export_text(m.get("text", ""))
            if not text.strip() and not links:
                continue
            self.append(chat_id, record(
                m["id"], m["date"], m.get("from") or "Unknown", text, links,
                m.get("reply_to_message_id"), export_media(m), export_uid(m),
            ))
            added += 1
        return chat_id, added


_LOG_MSG_RE = re.compile(r"\[MSG\] chat=\S+ chat_id=(-?\d+) from=(.+?) user_id=(\d+) text=")


def uids_from_logs(lines) -> dict[int, dict[str, int]]:
    """Строки [MSG] лога бота → chat_id → {имя автора: user_id}."""
    out: dict[int, dict[str, int]] = {}
    for line in lines:
        if (m := _LOG_MSG_RE.search(line)) and int(m.group(3)):
            out.setdefault(int(m.group(1)), {})[m.group(2)] = int(m.group(3))
    return out


def fill_uids_cli(data_dir: str, bot_id: int, bot_label: str, export_path: str, logs: list[str]) -> None:
    archive = ChatArchive(data_dir)
    names: dict[int, dict[str, int]] = {}
    for path in logs:
        with open(path, encoding="utf-8", errors="replace") as f:
            for chat_id, found in uids_from_logs(f).items():
                names.setdefault(chat_id, {}).update(found)
    by_id: dict[int, dict[int, int]] = {}
    if export_path != "-":
        with open(export_path, encoding="utf-8") as f:
            export = json.load(f)
        chat_id = -1000000000000 - int(export["id"])
        by_id[chat_id] = {m["id"]: u for m in export.get("messages", []) if (u := export_uid(m))}
    for name in os.listdir(os.path.join(data_dir, "chats")):
        try:
            chat_id = int(name)
        except ValueError:
            continue
        if not os.path.exists(archive.path(chat_id)):
            continue
        filled = archive.fill_uids(chat_id, by_id.get(chat_id, {}),
                                   {**names.get(chat_id, {}), bot_label: bot_id})
        print(f"chat {chat_id}: uid дописан в {filled} сообщений")


def main(argv: list[str]) -> int:
    if len(argv) >= 6 and argv[1] == "fill-uids":
        # fill-uids DATA_DIR BOT_ID EXPORT.json|- LOG...
        fill_uids_cli(argv[2], int(argv[3]), "Бот (ты)", argv[4], argv[5:])
        return 0
    if len(argv) < 3 or argv[1] != "import":
        print(__doc__)
        return 2
    data_dir = argv[3] if len(argv) > 3 else os.getenv("DATA_DIR", "data")
    with open(argv[2], encoding="utf-8") as f:
        export = json.load(f)
    chat_id, added = ChatArchive(data_dir).import_export(export)
    print(f"chat {chat_id}: добавлено {added} сообщений")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
