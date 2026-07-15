"""AI úprava přepisu přes Claude API (Haiku 4.5).

Druhá gramatická korektura: opraví interpunkci, kapitalizaci, pádové a koncovkové
chyby vzniklé při přepisu řeči, a zejména foneticky zkomolené anglické technické
termíny (např. „sommitnul" → „commitnul") — přesně to, co Whisper u CZ+EN
code-switchingu chybuje.

Chování při chybě (O6): metoda `clean` výjimku PROPAGUJE — volající (app.py)
ukáže viditelnou chybu a vloží syrový přepis, aby se text neztratil.
"""

from __future__ import annotations

DEFAULT_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = """Jsi korektor diktovaného textu. Dostaneš syrový přepis mluveného textu (z Whisperu) určený pro aplikaci: {app}.

Uprav ho takto:
- Odstraň výplňová slova (ehm, jako, prostě) a nedokončené začátky vět.
- Doplň interpunkci a kapitalizaci.
- Oprav gramatické, pádové a koncovkové chyby vzniklé při přepisu řeči.
- Anglické technické termíny ponech v angličtině; oprav jen jejich foneticky zkomolený přepis (např. „sommitnul" → „commitnul", „pool request" → „pull request"). Nepřekládej je do češtiny.
- Zachovej autorův styl, tón a význam; nepřidávej vlastní obsah.
- Přizpůsob formálnost cílové aplikaci (Slack/chat = neformální, e-mail = formálnější).

Vrať POUZE upravený text, bez uvozovek a bez jakéhokoli komentáře."""


class Cleaner:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def clean(self, text: str, app_name: str | None = None) -> str:
        if not text.strip():
            return ""
        system = _SYSTEM_PROMPT.format(app=app_name or "neznámá")
        # max_tokens s rezervou nad délku vstupu; přepis bývá krátký.
        max_tokens = max(256, min(4096, len(text) // 2 + 512))
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
