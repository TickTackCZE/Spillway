"""Jedno místo pro posílání JavaScriptu do oken (WKWebView).

Všechna okna aplikace jsou WKWebView a všechna potřebují totéž: poslat do
stránky volání a nezamlčet chybu. Dřív měl každý modul vlastní kopii téhle
funkce — a když se v ní našla chyba, opravila se jen jedna ze tří.

Dvě věci, na kterých už doručení stavu selhalo:

1. Volání se předávalo bez completion handleru, takže výjimka v JS zmizela
   beze stopy a okno tiše ukazovalo zastaralý stav.
2. Pak přibyla pojistka „do načítající se stránky neposílej" — a rovnou rozbila
   plnění oken: `isLoading()` je ještě `True` ve chvíli, kdy `DOMContentLoaded`
   už proběhl (změřeno: přesně jeden tik). Push se stavem přišel do té škvíry,
   zahodil se a okno zůstalo na „Zjišťuji…" navždy.

Proto se tady **nic nezahazuje**: dokud se stránka načítá, volání se odloží
a zkusí znovu.
"""

from __future__ import annotations

from PyObjCTools import AppHelper

# Jak dlouho čekat na načtení stránky, než to vzdáme (40 × 0,15 s ≈ 6 s).
_MAX_TRIES = 40
_RETRY_S = 0.15


def run_js(webview, js: str, what: str = "", _tries: int = 0) -> None:
    """Spustí `js` v okně; chybu i nedoručení nahlásí do logu.

    `what` je krátký popis pro log („model", „notice") — bez něj se u tří oken
    nepozná, které z nich selhalo.
    """
    if webview is None:
        return
    try:
        loading = bool(webview.isLoading())
    except Exception:  # noqa: BLE001 — když se stav nedá zjistit, prostě pošli
        loading = False

    if loading:
        if _tries < _MAX_TRIES:
            AppHelper.callLater(_RETRY_S, lambda: run_js(webview, js, what, _tries + 1))
        else:
            print(f"❌ JS nedoručen{_tag(what)}: stránka se nenačetla")
        return

    def done(_result, err) -> None:
        if err is not None:
            print(f"❌ JS selhal{_tag(what)}: {err}")

    try:
        webview.evaluateJavaScript_completionHandler_(js, done)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ JS nešlo spustit{_tag(what)}: {exc}")


def measure(webview, js: str, on_value, what: str = "") -> None:
    """Změří něco v DOM a výsledek předá do `on_value` — až je stránka hotová.

    Pro případy „změř kartu a podle toho nastav nativní okno". Musí to jít přes
    stejné odkládání jako `run_js`, a to ze dvou důvodů:

    1. Na nenačtené stránce `document.querySelector(...)` vrátí `null` a měření
       spadne (`TypeError`), takže okno zůstane ve výchozí velikosti.
    2. `run_js` volání do nenačtené stránky ODKLÁDÁ. Kdyby měření šlo přímo,
       předběhlo by `setState`, který ho teprve nastavuje — a naměřilo by
       předchozí podobu.

    `js` musí vracet řetězec (`JSON.stringify(...)`) nebo číslo; pole čísel se
    z `evaluateJavaScript` nevrací spolehlivě (ověřeno: přijde `None`).
    """
    def done(value, err) -> None:
        if err is not None:
            print(f"❌ měření selhalo{_tag(what)}: {err}")
            return
        if value is None:
            return
        try:
            on_value(value)
        except Exception as exc:  # noqa: BLE001 — měření nesmí nic shodit
            print(f"❌ měření nešlo použít{_tag(what)}: {exc}")

    _when_loaded(webview, lambda: _evaluate(webview, js, done, what), what)


def _when_loaded(webview, fn, what: str, _tries: int = 0) -> None:
    """Zavolá `fn`, jakmile stránka doběhne (stejný strop jako `run_js`)."""
    if webview is None:
        return
    try:
        loading = bool(webview.isLoading())
    except Exception:  # noqa: BLE001
        loading = False
    if not loading:
        fn()
        return
    if _tries < _MAX_TRIES:
        AppHelper.callLater(_RETRY_S, lambda: _when_loaded(webview, fn, what, _tries + 1))
    else:
        print(f"❌ měření nedoručeno{_tag(what)}: stránka se nenačetla")


def _evaluate(webview, js: str, done, what: str) -> None:
    try:
        webview.evaluateJavaScript_completionHandler_(js, done)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ měření nešlo spustit{_tag(what)}: {exc}")


def _tag(what: str) -> str:
    return f" ({what})" if what else ""
