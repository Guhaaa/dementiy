"""Вики бота о чатах: люди, чаты, темы и сам бот — страницы markdown со ссылками.

DATA_DIR/wiki/ ведёт агент Codex (песочница workspace-write только в этой папке).
Правила вики — в AGENTS.md, Codex читает их сам. Бот кладёт в _inbox/ пачку
сообщений из архива чата и просит внести её в вики:

- старая история (до WIKI_DAILY_SINCE) — одной пачкой, нарезанной на части по порядку;
- дальше — по дню; каждую ночь дописывается прошедший день.

Механики взяты из babaev-ai-systems/wiki-platform: каркас правил (цели, обязательные
сигналы, что не сохранять, ограничения), журнал обработки с картой покрытия,
различие даты обработки и даты события, чтение большого источника по частям
и проверка ссылок кодом после агента.

Раз в неделю проходит чистка: дубли, битые ссылки, устаревшее, длинные страницы.
В ответах бот вики только читает. Личка в вики не попадает.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, timedelta
from typing import Awaitable, Callable

# (prompt, workdir) → ответ агента
Agent = Callable[[str, str], Awaitable[str]]

MAX_BATCH_CHARS = 120_000
HISTORY = "0000-history"  # ключ пачки старой истории: сортируется раньше дат
HISTORY_PART_LINES = 400
LINT_EVERY_DAYS = 7

RULES = """# Вики чатов

## Цели вики

Это память бота, который в групповых чатах играет Максима Дементьева. Вики ведёшь ты.
Бот читает её перед ответом, чтобы понимать, кто есть кто, что происходило в чатах,
что он сам говорил и обещал, — и вести себя как один человек во всех чатах.
В сообщениях бот подписан «Бот (ты)». «Максим Дементьев» — настоящий Максим: его слова
о себе и его взгляды — факты о том, кого бот играет. На его странице это отметь.

## Обязательные сигналы
- кто есть кто: работа, город, интересы, семья и планы, если человек сам о них говорил;
- отношения: кто с кем дружит, спорит, шутит; кто кого как называет;
- обещания и договорённости: кто, кому, что, когда; выполнены ли;
- границы: что человеку неприятно, о чём он просил не говорить, что не любит в боте;
- позиции: что человек думает о повторяющихся темах;
- постоянные шутки, мемы и словечки чата.

## Никогда не сохранять
- пароли, токены, ключи, номера карт и документов;
- то, что бот только предположил: в вики — только то, что есть в сообщениях.

## Ограничения интерпретации
- Шутка, мем и подкол — не факт о человеке и не его оценка.
- Дата события — это дата сообщения, а не дата обработки.
  Старые сообщения дополняют историю и не отменяют более новые сведения.

## Страницы
- `index.md` — каталог: по строке на страницу, `- [[people/810801]] Guha — кто это в двух словах`.
  Держи его в соответствии со списком файлов.
- `people/<id>.md` — человек, имя файла — его Telegram id. Заголовок — основное имя.
  Дальше: «Имена» (как подписывается в разных чатах), «Чаты», факты о нём (работа, город,
  интересы, планы, взгляды), отношения с другими людьми, как с ним говорить,
  что бот ему обещал или с ним обсуждал.
- `chats/<chat_id>.md` — чат: о чём он, кто там бывает, правила, настроение, постоянные шутки.
- `topics/<slug>.md` — тема, мем, событие или спор, которые всплывают больше одного раза.
  slug — латиницей через дефис. Отдельных страниц для разовых тем не заводи.
- `self.md` — сам бот: как к нему относятся, его позиции по темам, обещания (где, когда, кому).
- `log.md` — журнал обработки: `## <чат> <период>`, затем «Изменено:» — список страниц,
  и «Пропущено:» — какие крупные темы пачки не записаны и почему (или «пропусков нет»).

## Правила
- Человека узнавай по id, не по имени: одного человека подписывают по-разному
  (по-русски и латиницей). Одна страница на id. Авторов без id упоминай на странице чата.
- У каждого факта в конце строки — источник: `(<chat_id> #<номер сообщения>, <дата>)`.
- Ссылки на другие страницы — `[[people/810801]]`, `[[topics/foto-v-bane]]`, без `.md`.
- Пиши кратко и по фактам, а не пересказ переписки. Мелочи на один раз не записывай.
- Новое противоречит старому — исправь страницу; если важно, как менялось, оставь пометку с датой.
- Страница длиннее ~4000 знаков — сожми её, сохранив главное.
- Чувствительное (здоровье, деньги, семья) пиши, только если человек сам рассказал об этом
  в чате, и без оценок.
- Меняй только файлы вики. Файлы в `_inbox/` не меняй и не удаляй.
"""

INGEST_PROMPT = """Новые сообщения чата «{title}» (chat_id {chat_id}) за {period}: {files}.
Строка: `[ГГГГ-ММ-ДД чч:мм #номер Имя (id N) ↩номер_ответа]: текст`.
Внеси в вики всё важное по правилам AGENTS.md: страницы людей, чата, тем и self.md,
затем index.md и log.md. В конце ответь одной строкой, какие страницы изменил."""

HISTORY_NOTE = """Это вся старая история чата, она нарезана на части. Читай их строго по порядку,
каждую целиком, и вноси в вики по ходу, не дожидаясь конца. Не пропускай части."""

LINT_PROMPT = """Проведи чистку вики по правилам AGENTS.md: слей дубли (одному id — одна страница),
исправь битые [[ссылки]], убери устаревшее, сожми страницы длиннее ~4000 знаков,
сверь index.md со списком файлов. Запиши в log.md, что сделал. В конце ответь одной строкой."""


def message_lines(records: list[dict], limit: int = 1500) -> list[str]:
    """Сообщение строкой: `[ГГГГ-ММ-ДД чч:мм #номер Имя (id N) ↩ответ_на]: текст`."""
    out = []
    for r in records:
        uid = f" (id {r['uid']})" if r.get("uid") else ""
        reply = f" ↩{r['reply_to']}" if r.get("reply_to") else ""
        media = f"[{r['media']}] " if r.get("media") else ""
        stamp = r["date"][:16].replace("T", " ")
        text = r["text"][:limit].replace("\n", " ")
        out.append(f"[{stamp} #{r['id']} {r['from']}{uid}{reply}]: {media}{text}")
    return out


def format_batch(records: list[dict]) -> str:
    """Сообщения дня; если пачка не влезает, длинные сообщения обрезаются."""
    for limit in (1500, 800, 400, 200):
        if len(text := "\n".join(message_lines(records, limit))) <= MAX_BATCH_CHARS:
            return text
    return text[-MAX_BATCH_CHARS:]


def batch_key(day: str, daily_since: str) -> str:
    """Пачка, в которую попадает день: сам день или вся старая история."""
    return day if day >= daily_since else HISTORY


_LINK_RE = re.compile(r"\[\[([^\]|#]+)")


def broken_links(root: str) -> list[str]:
    """«страница → [[ссылка]]» для ссылок на несуществующие страницы."""
    out = []
    for folder, _, files in os.walk(root):
        if "_inbox" in folder:
            continue
        for name in files:
            if not name.endswith(".md") or name == "AGENTS.md":
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for link in _LINK_RE.findall(text):
                if not os.path.exists(os.path.join(root, link.strip() + ".md")):
                    out.append(f"{os.path.relpath(path, root)} → [[{link.strip()}]]")
    return out


class Wiki:
    def __init__(self, data_dir: str, daily_since: str):
        self.root = os.path.abspath(os.path.join(data_dir, "wiki"))
        self.daily_since = daily_since
        self.state_path = os.path.join(os.path.abspath(data_dir), "wiki-state.json")
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
        except FileNotFoundError:
            state = {}
        self.done: dict[str, str] = state.get("done", {})
        self.titles: dict[str, str] = state.get("titles", {})
        self.last_lint: str = state.get("last_lint", "")

    def _save(self) -> None:
        directory = os.path.dirname(self.state_path)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"done": self.done, "titles": self.titles, "last_lint": self.last_lint},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    @property
    def index_path(self) -> str:
        return os.path.join(self.root, "index.md")

    def prepare(self) -> None:
        """Папка вики и актуальные правила (AGENTS.md переписывается при каждом запуске)."""
        os.makedirs(os.path.join(self.root, "_inbox"), exist_ok=True)
        with open(os.path.join(self.root, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write(RULES)

    def set_title(self, chat_id: int, title: str) -> None:
        if title and self.titles.get(str(chat_id)) != title:
            self.titles[str(chat_id)] = title
            self._save()

    def title(self, chat_id: int) -> str:
        return self.titles.get(str(chat_id), str(chat_id))

    def pending(self, chats: dict[int, list[dict]], today: str) -> list[tuple[str, int, list[dict]]]:
        """Необработанные пачки всех чатов по порядку дат: (ключ, chat_id, сообщения).
        Сегодняшний день не берётся — он ещё не закончился."""
        batches: dict[tuple[str, int], list[dict]] = {}
        for chat_id, records in chats.items():
            done = self.done.get(str(chat_id), "")
            for r in records:
                day = r["date"][:10]
                if done < day < today:
                    batches.setdefault((batch_key(day, self.daily_since), chat_id), []).append(r)
        return [(key, chat_id, msgs) for (key, chat_id), msgs in sorted(batches.items())]

    async def ingest(self, chat_id: int, key: str, records: list[dict], agent: Agent) -> str:
        """Одна пачка сообщений → правки вики. Возвращает ответ агента."""
        first = min(r["date"][:10] for r in records)
        last = max(r["date"][:10] for r in records)
        period = first if first == last else f"{first} — {last}"
        history = key == HISTORY
        if history:  # вся история целиком, частями по HISTORY_PART_LINES строк
            lines = message_lines(records)
            parts = ["\n".join(lines[i:i + HISTORY_PART_LINES]) for i in range(0, len(lines), HISTORY_PART_LINES)]
        else:
            parts = [format_batch(records)]
        names = [os.path.join("_inbox", f"{chat_id}_{key}_{n:03d}.txt") for n in range(1, len(parts) + 1)]
        for name, part in zip(names, parts):
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
                f.write(part)
        files = f"файл {names[0]}" if len(names) == 1 else f"{len(names)} файлов, по порядку: {', '.join(names)}"
        prompt = INGEST_PROMPT.format(title=self.title(chat_id), chat_id=chat_id, period=period, files=files)
        if history:
            prompt += "\n\n" + HISTORY_NOTE
        try:
            answer = await agent(prompt, self.root)
        finally:
            for name in names:
                os.unlink(os.path.join(self.root, name))
        self.done[str(chat_id)] = last
        self._save()
        return answer

    async def lint_if_due(self, today: str, agent: Agent) -> str | None:
        if self.last_lint and date.fromisoformat(today) - date.fromisoformat(self.last_lint) < timedelta(days=LINT_EVERY_DAYS):
            return None
        if not os.path.exists(self.index_path):
            return None
        prompt = LINT_PROMPT
        if broken := broken_links(self.root):
            prompt += "\n\nБитые ссылки, найденные проверкой:\n" + "\n".join(f"- {b}" for b in broken[:200])
        answer = await agent(prompt, self.root)
        self.last_lint = today
        self._save()
        return answer

    def hint(self) -> str:
        """Где вики; пусто, пока вики нет."""
        if not os.path.exists(self.index_path):
            return ""
        return (
            f"У тебя есть вики {self.root}: там описано всё, что с тобой происходило в чатах, — "
            "люди (people/<id>.md по Telegram id), чаты, темы и ты сам (self.md); каталог — index.md. "
            "Пользуйся по своему усмотрению. Файлы не меняй."
        )
