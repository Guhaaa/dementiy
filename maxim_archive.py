"""Архив сообщений чата: DATA_DIR/chats/<chat_id>/archive.jsonl, по сообщению в строке.

Это рабочий каталог сессии Codex этого чата, поэтому Codex ищет по архиву
grep'ом: не было ли уже этой новости, и даёт ссылку на найденное сообщение.
Бот дописывает каждое сообщение группы; старую историю добавляет импорт
выгрузки Telegram (JSON из Telegram Desktop):

    python3 maxim_archive.py import result.json [DATA_DIR]
"""

from __future__ import annotations

import json
import os
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
           links: list[str] | None = None, reply_to: int | None = None, media: str = "") -> dict:
    """media — вложение, которого в архиве нет (часто новость приходит скриншотом)."""
    rec = {"id": msg_id, "date": date, "from": sender, "text": text[:MAX_TEXT]}
    if media:
        rec["media"] = media
    if links:
        rec["links"] = links
    if reply_to:
        rec["reply_to"] = reply_to
    return rec


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
        try:
            with open(self.path(chat_id), encoding="utf-8") as f:
                return {json.loads(line)["id"] for line in f if line.strip()}
        except FileNotFoundError:
            return set()

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
                m.get("reply_to_message_id"), export_media(m),
            ))
            added += 1
        return chat_id, added


def main(argv: list[str]) -> int:
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
