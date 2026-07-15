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

# Modely, které mají adaptivní myšlení zapnuté by default → u krátké korektury
# ho vypneme (rychlost + cena).
_THINKING_ON = ("claude-sonnet-5", "claude-opus-4", "claude-fable-5")

_SYSTEM_PROMPT = """Jsi korektor diktovaného textu a děláš MINIMÁLNÍ úpravy. Dostaneš syrový přepis mluveného textu z Whisperu, určený pro aplikaci: {app}.

Uprav POUZE tyto věci:
- Doplň interpunkci (tečky, čárky, otazníky) a velká písmena na začátcích vět a u vlastních jmen.
- Odstraň zjevná výplňová slova a zaškobrtnutí řeči („ehm", „éé", vycpávkové „no", zdvojené či nedokončené začátky vět).
- Oprav gramatickou shodu (pády, koncovky, rod, číslo) TAM, kde je zamýšlené slovo jednoznačné.
- Oprav foneticky zkomolené ANGLICKÉ technické termíny, ale JEN když je správný tvar zřejmý z kontextu (např. „sommitnul" → „commitnul", „pool request" → „pull request", „endpoint", „deployment").

PŘÍSNÁ PRAVIDLA (dodržuj bezvýhradně):
- NEPŘEFORMULOVÁVEJ. Neměň slovosled, výběr slov ani styl. Zachovej autorovu formulaci i tam, kde je neobratná.
- NEHÁDEJ VÝZNAM. Když nějaké slovo vypadá jako přeslech nebo nesmysl, ale nevíš JISTĚ, co bylo míněno, nech ho BEZE ZMĚNY. Je lepší ponechat divné slovo než ho nahradit něčím, co jsi si domyslel.
- NIKDY nevynechávej ani nepřidávej obsahová slova. Každé podstatné jméno, sloveso a vlastní jméno musí zůstat zachováno.
- Anglické termíny nepřekládej do češtiny.

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
        kwargs: dict = {}
        # U korektury nechceme „myšlení" — jen rychlou přímou úpravu.
        if any(self.model.startswith(m) for m in _THINKING_ON):
            kwargs["thinking"] = {"type": "disabled"}
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": text}],
            **kwargs,
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
