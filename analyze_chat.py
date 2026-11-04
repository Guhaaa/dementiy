#!/usr/bin/env python3
"""Анализ стиля автора по JSON-выгрузке Telegram (Desktop → Export chat history → JSON).

Пример:
    python3 analyze_chat.py result.json --author "Максим Дементьев" --out report.md

Скрипт делит сообщения автора на разговорные и вставки (промпты, ответы
моделей, код, английские тексты, пересылки), считает метрики манеры речи,
частоты известных оборотов и предлагает кандидатов: частые начала, n-граммы,
цитаты в кавычках. Кандидатов надо проверить руками, прежде чем добавлять
в maxim_style.py.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys

# Известные обороты: регэксп по тексту в нижнем регистре
KNOWN_PHRASES = {
    "я не знаю": r"\bя\s+не\s+знаю\b",
    "насколько я знаю": r"\bнасколько\s+я\s+знаю\b",
    "если я правильно понимаю/понял": r"\bесли\s+я\s+правильно\s+понима|\bесли\s+я\s+правильно\s+понял",
    "на мой взгляд": r"\bна\s+мой\s+взгляд\b",
    "на самом деле": r"\bна\s+самом\s+деле\b",
    "т.е.": r"(?<!\w)т\.\s*е\.",
    "то есть": r"\bто\s+есть\b",
    "в целом": r"\bв\s+целом\b",
    "причём": r"\bприч[её]м\b",
    "в результате": r"\bв\s+результате\b",
    "по поводу": r"\bпо\s+поводу\b",
    "не факт, что": r"\bне\s+факт\b",
    "до сих пор": r"\bдо\s+сих\s+пор\b",
    "кстати": r"\bкстати\b",
    "короче": r"\bкороче\b",
    "в общем": r"\bв\s+общем\b",
    "по-моему": r"\bпо-моему\b",
    "думаю": r"\bдумаю\b",
    "интересно": r"\bинтересно\b",
}

TOPICS = {
    "LLM/промпты": r"\b(?:llm|промпт|prompt|модел|нейросет|контекст|токен|агент)",
    "Claude/Codex": r"\b(?:claude|клод|codex|кодекс|anthropic|opus|sonnet)",
    "ChatGPT/OpenAI": r"\b(?:chatgpt|gpt|openai|чатгпт)",
    "Gemini/Google": r"\b(?:gemini|гемини|джемини|google|гугл)",
    "код/разработка": r"\b(?:код|python|питон|c\+\+|компил|отлад|баг|тест|git|скрипт)",
    "Linux/мультимедиа": r"\b(?:linux|линукс|wayland|gstreamer|pipewire|ubuntu|debian)",
    "язык/перевод": r"\b(?:перевод|переве|язык|слово|фраз|english|французск)",
    "кино/книги/музыка": r"\b(?:фильм|кино|книг|музык|песн|толст|пушкин)",
    "работа/заказчики": r"\b(?:работ|заказчик|клиент|контракт|деньг|зарплат)",
}

PROFANITY_RE = re.compile(r"(?:хуй|хуйн|хуе|заеб|пизд|бля|ебан|ёбан|охуе)", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
URL_ONLY_RE = re.compile(r"^\s*https?://\S+\s*$")
QUOTED_RE = re.compile(r'^\s*["«„](.{6,160}?)["»“]\s*[.!?…]*\s*$', re.S)
WORD_RE = re.compile(r"[a-zа-яё]+(?:[-'][a-zа-яё]+)*", re.I)


def flat_text(message: dict) -> str:
    text = message.get("text", "")
    if isinstance(text, str):
        return text
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in text)


def has_code(message: dict) -> bool:
    text = message.get("text")
    return isinstance(text, list) and any(
        isinstance(p, dict) and p.get("type") in {"pre", "code"} for p in text
    )


def latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum("a" <= c.lower() <= "z" for c in letters) / len(letters)


def paste_reason(message: dict, text: str) -> str | None:
    """Причина считать сообщение вставкой, а не собственной речью автора."""
    if message.get("forwarded_from"):
        return "пересылка"
    if has_code(message):
        return "код"
    if len(text) > 700:
        return "длинное (>700)"
    if len(text) > 200 and latin_share(text) > 0.6:
        return "английский текст"
    if URL_ONLY_RE.match(text):
        return "только ссылка"
    return None


def percentile(values: list[int], q: float) -> int:
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def ngrams(words: list[str], n: int):
    return (" ".join(words[i:i + n]) for i in range(len(words) - n + 1))


def analyze(data: dict, author: str, min_count: int) -> str:
    messages = [m for m in data.get("messages", []) if m.get("type") == "message"]
    by_id = {m["id"]: m for m in messages}
    own = [m for m in messages if m.get("from") == author]
    if not own:
        raise SystemExit(f"Нет сообщений автора {author!r}")
    author_ids = {m.get("from_id") for m in own}

    talk, pasted = [], collections.Counter()
    full_texts = []
    for m in own:
        text = flat_text(m).strip()
        if not text:
            continue
        full_texts.append(text)
        reason = paste_reason(m, text)
        if reason:
            pasted[reason] += 1
        else:
            talk.append((m, text))

    lengths = [len(t) for _, t in talk]
    n = len(talk)

    def share(pred) -> str:
        return f"{100 * sum(1 for _, t in talk if pred(t)) / n:.1f}%"

    lines = [
        f"# Анализ стиля: {author}",
        "",
        f"Источник: чат «{data.get('name', '?')}», "
        f"{own[0]['date'][:10]} — {own[-1]['date'][:10]}.",
        "",
        "## Корпус",
        "",
        f"- Сообщений автора: {len(own)}, с текстом: {len(full_texts)}.",
        f"- Вставки исключены из метрик стиля: {sum(pasted.values())} "
        f"({', '.join(f'{k} — {v}' for k, v in pasted.most_common())}).",
        f"- Разговорных сообщений: {n}.",
        "",
        "## Метрики",
        "",
        "| Признак | Значение |",
        "|---|---:|",
        f"| Медиана длины | {int(statistics.median(lengths))} символов |",
        f"| 75-й перцентиль | {percentile(lengths, 0.75)} символов |",
        f"| 90-й перцентиль | {percentile(lengths, 0.90)} символов |",
        f"| С вопросом | {share(lambda t: '?' in t)} |",
        f"| С восклицанием | {share(lambda t: '!' in t)} |",
        f"| С многоточием | {share(lambda t: '...' in t or '…' in t)} |",
        f"| Русский + английский | {share(lambda t: re.search('[а-яё]', t, re.I) and re.search('[a-z]{3,}', t, re.I))} |",
        f"| С эмодзи | {share(lambda t: EMOJI_RE.search(t))} |",
        f"| С матом | {share(lambda t: PROFANITY_RE.search(t))} |",
        "",
        "## Известные обороты (разговорный подкорпус)",
        "",
    ]
    lowered = [t.lower() for _, t in talk]
    for name, pattern in KNOWN_PHRASES.items():
        count = sum(1 for t in lowered if re.search(pattern, t))
        lines.append(f"- `{name}` — {count}")

    openers = collections.Counter()
    grams = collections.Counter()
    for t in lowered:
        words = WORD_RE.findall(t)
        if len(words) >= 2:
            openers[" ".join(words[:2])] += 1
        seen = set()
        for size in (3, 4, 5):
            seen.update(ngrams(words, size))
        grams.update(seen)  # считаем один раз на сообщение

    lines += ["", f"## Частые начала (2 слова, ≥{min_count})", ""]
    lines += [f"- `{k}` — {v}" for k, v in openers.most_common(40) if v >= min_count]

    lines += ["", f"## Частые n-граммы 3–5 слов (≥{min_count} сообщений)", ""]
    picked: list[tuple[str, int]] = []
    for gram, count in grams.most_common():
        if count < min_count:
            break
        # длинную n-грамму оставляем, короткую внутри неё с тем же счётом — нет
        if any(gram in longer and count == c for longer, c in picked):
            continue
        picked = [(g, c) for g, c in picked if not (g in gram and c == count)]
        picked.append((gram, count))
    picked.sort(key=lambda gc: -gc[1])
    lines += [f"- `{g}` — {c}" for g, c in picked[:60]]

    lines += ["", "## Цитаты в кавычках (кандидаты)", ""]
    quotes = collections.Counter()
    for _, t in talk:
        match = QUOTED_RE.match(t)
        if match:
            quotes[match.group(1).strip()] += 1
    lines += [f"- «{q}»" + (f" ×{c}" if c > 1 else "") for q, c in quotes.most_common()]

    lines += ["", "## Короткие восклицания (≤60 символов, кандидаты)", ""]
    exclaims = collections.Counter(
        t for _, t in talk if t.endswith("!") and len(t) <= 60 and not QUOTED_RE.match(t)
    )
    lines += [
        f"- {t.replace(chr(10), ' / ')}" + (f" ×{c}" if c > 1 else "")
        for t, c in exclaims.most_common(80)
    ]

    lines += ["", "## Темы (весь корпус, сообщений с упоминанием)", ""]
    all_lower = [t.lower() for t in full_texts]
    for name, pattern in TOPICS.items():
        lines.append(f"- {name} — {sum(1 for t in all_lower if re.search(pattern, t))}")

    replied = collections.Counter()
    for m, _ in talk:
        target = by_id.get(m.get("reply_to_message_id"))
        if target and target.get("from_id") not in author_ids:
            replied[target.get("from") or "?"] += 1
    lines += ["", "## Кому автор отвечает reply", ""]
    lines += [f"- {who} — {c}" for who, c in replied.most_common(10)]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", help="result.json из Telegram Desktop")
    parser.add_argument("--author", default="Максим Дементьев")
    parser.add_argument("--min-count", type=int, default=4)
    parser.add_argument("--out", help="файл отчёта (по умолчанию stdout)")
    args = parser.parse_args()
    with open(args.export, encoding="utf-8") as f:
        report = analyze(json.load(f), args.author, args.min_count)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
