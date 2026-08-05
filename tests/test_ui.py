"""Testy vzhledu — ikona v liště, okno nastavení, nápověda, popover.

Oddělené od logiky schválně: kontrolují **skladbu a geometrii** (že se HTML
poskládá, že tlačítka mají jednu šířku, že se snímky ikony liší), ne chování
pipeline. Nespouštějí WebKit ani okna — jen čtou vygenerovaný HTML a počítají
souřadnice, takže běží i bez GUI.
"""

import pytest


def test_level_step_maps_into_frame_range():
    from spillway import baricon

    assert baricon.level_step(0.0) == 0
    assert baricon.level_step(1.0) == baricon.LEVEL_STEPS - 1
    assert baricon.level_step(2.5) == baricon.LEVEL_STEPS - 1, "musí ořezat"
    assert baricon.level_step(-1.0) == 0
    assert baricon.level_step(float("nan")) == 0


def test_bars_scaled_keeps_centers_and_shrinks_height():
    from spillway import design

    full = design.scaled_bars(1.0)
    assert full == design._WAVE_BARS, "k=1 musí dát přesně původní logo"

    half = design.scaled_bars(0.5)
    for (x0, t0, b0), (x1, t1, b1) in zip(design._WAVE_BARS, half, strict=True):
        assert x1 == x0, "sloupce se nesmí posouvat do stran"
        assert (t1 + b1) / 2 == pytest.approx((t0 + b0) / 2), "střed zůstává"
        assert (b1 - t1) == pytest.approx((b0 - t0) / 2)


def test_frame_scales_distinguish_states():
    from spillway import baricon

    rec = [baricon._scale_for("rec", i) for i in range(baricon.LEVEL_STEPS)]
    assert rec == sorted(rec), "hlasitěji = vyšší sloupce"
    assert rec[-1] == 1.0 and rec[0] > 0, "v tichu zbyde aspoň řádka teček"

    assert baricon._scale_for("idle", 0) == 1.0, "klid = základní logo"
    assert baricon._scale_for("cancel", 0) < 0.5


def _tallest_bar(bars) -> int:
    heights = [b - t for _, t, b in bars]
    return heights.index(max(heights))


def test_processing_wave_travels_left_to_right():
    from spillway import baricon, design

    peaks = [_tallest_bar(design.wave_bars(i, baricon.PULSE_FRAMES)) for i in range(baricon.PULSE_FRAMES)]
    # Hřeben musí obejít celou vlnovku — jinak to není běžící vlna, ale blikání.
    assert len(set(peaks)) == baricon.PULSE_FRAMES, f"hřeben stojí: {peaks}"

    # …a postupovat doprava (s přetečením na začátek, protože se to zacyklí).
    n = len(design.wave_bars(0, baricon.PULSE_FRAMES))
    steps = [(b - a) % n for a, b in zip(peaks, peaks[1:], strict=False)]
    assert all(s == steps[0] for s in steps), f"vlna nejde rovnoměrně: {peaks}"
    assert steps[0] == 1, f"hřeben se má posouvat o sloupec doprava, jde o {steps[0]}"


def test_processing_wave_loops_seamlessly_and_stays_calm():
    from spillway import baricon, design

    assert design.wave_bars(0, baricon.PULSE_FRAMES) == design.wave_bars(baricon.PULSE_FRAMES, baricon.PULSE_FRAMES), (
        "poslední snímek musí navázat na první, jinak animace cukne"
    )

    full = {b - t for _, t, b in design.scaled_bars(1.0)}
    wave = [
        b - t
        for i in range(baricon.PULSE_FRAMES)
        for _, t, b in design.wave_bars(i, baricon.PULSE_FRAMES)
    ]
    # Zpracování nesmí vypadat jako plná výchylka ukazatele hlasitosti.
    assert max(wave) < max(full), "vlna nesmí dosáhnout výšky základního loga"
    assert min(wave) > 0, "sloupce nesmí zmizet úplně"


def test_no_field_dictation_keeps_hud_at_icon_for_whole_flow():
    from spillway.app import Controller

    # Rozhodnutí „diktuje se bez pole" padne jednou na začátku a drží celý
    # diktát — jinak by okénko během zpracování poskakovalo podle toho, co má
    # zrovna fokus, místo aby zůstalo pod ikonou až po „Připraveno k vložení".
    c = Controller.__new__(Controller)
    assert getattr(c, "no_field", False) is False, "výchozí stav = diktuje se do pole"

    c.no_field = True
    c.target_bundle = "com.apple.finder"

    # Tohle je přesně podmínka, kterou tray počítá pro polohu okénka.
    left_app = False
    assert left_app or c.no_field, "bez pole musí okénko k ikoně i bez odchodu z appky"


def test_logo_has_no_drops():
    from spillway import design

    # Kapky pod vlnou se v malých velikostech slily a do loga nepatří.
    svg = design.logo_svg()
    assert "<circle" not in svg, "logo nesmí obsahovat kapky"
    assert svg.count("<rect") == len(design._WAVE_BARS)


def test_bars_svg_is_wellformed_and_uses_shared_geometry():
    from spillway import baricon, design

    svg = design.bars_svg(design.scaled_bars(0.5), "#FF0000", 24, 24)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'viewBox="0 0 100 100"' in svg and 'fill="#FF0000"' in svg

    # Ikona v liště i schémata v nápovědě musí kreslit z týchž funkcí, jinak
    # se rozejdou a nápověda přestane odpovídat tomu, co uživatel vidí.
    assert baricon._bars_for("idle", 0) == design.scaled_bars(1.0)
    assert baricon._bars_for("proc", 3) == design.wave_bars(
        3, baricon.PULSE_FRAMES, baricon._WAVE_LO, baricon._WAVE_HI
    )


def test_settings_window_has_both_pages_and_no_leftover_placeholders():
    from spillway import settings_window as sw

    html = sw._HTML
    for marker in ("pageSettings", "pageHelp", "showPage(", "saveUnload("):
        assert marker in html, marker
    # Placeholdery se musí všechny vyřešit, jinak by v okně svítilo „__IC_REC__".
    assert "__" not in html.replace("__", "", 0) or not any(
        t in html for t in ("__LOGO__", "__LANGS__", "__IC_IDLE__", "__IC_REC__",
                            "__IC_PROC__", "__IC_CANCEL__")
    )


def test_settings_window_offers_unload_field_within_allowed_range():
    from spillway import config
    from spillway import settings_window as sw

    html = sw._HTML
    assert 'id="unload"' in html
    # Meze v nápovědě musí odpovídat tomu, co skutečně vynucuje config.
    assert f"{config.AUTO_UNLOAD_MIN_SEC}–{config.AUTO_UNLOAD_MAX_SEC}" in html


def test_popover_footer_actions():
    from spillway import popover

    html = popover._HTML if hasattr(popover, "_HTML") else popover.HTML
    assert "Nastavení…" not in html, "tři tečky pryč"
    assert ">Nastavení<" in html and ">Nápověda<" in html
    # Konec je jediná nevratná akce → musí být barevně oddělený.
    assert 'class="danger"' in html and "open_help" in html
    assert "--danger:#E11D48" in html, "červená z Domovoy palety"


def test_help_shows_no_hardcoded_configurable_keys():
    from spillway import settings_window as sw

    html = sw._HTML
    # Nastavitelné klávesy se v nápovědě nesmí psát natvrdo — po změně v
    # Nastavení by v nápovědě zůstala stará hodnota.
    help_part = html[html.index('id="pageHelp"'):html.index("/pageHelp")]
    for token in (">F5<", ">Escape<"):
        for occurrence in range(help_part.count(token)):
            idx = -1
            for _ in range(occurrence + 1):
                idx = help_part.index(token, idx + 1)
            snippet = help_part[max(0, idx - 90):idx]
            assert ('class="kbd hk"' in snippet or 'class="kbd ck"' in snippet
                    or 'id="helpHotkey"' in snippet or 'id="helpCancel"' in snippet), (
                f"natvrdo napsaná klávesa {token} v nápovědě: …{snippet[-70:]}"
            )
    # ⌘V je systémová zkratka pro vložení, ta se nenastavuje — smí být natvrdo.
    assert "⌘V" in help_part


def test_help_has_no_orphan_punctuation_or_inline_emphasis():
    import re

    from spillway import settings_window as sw

    part = sw._HTML[sw._HTML.index('id="pageHelp"'):sw._HTML.index("/pageHelp")]

    # Zvýraznění uprostřed věty láme řádek a interpunkce za ním padá na začátek
    # dalšího — přesně tohle vypadalo v krabičce „Úprava" rozbitě.
    assert not re.findall(r"<span>[^<]*<b>.*?</b>[^<]*</span>", part), (
        "v krabičkách nesmí být zvýraznění uprostřed věty"
    )

    # Pomlčky, lomítka a čárky musí být svázané s předchozím slovem, jinak
    # můžou skončit samy na začátku řádku.
    text = re.sub(r"<[^>]+>", " ", part)
    orphans = re.findall(r"(?<!&nbsp;)\s([—–+·×/,;])\s", text)
    assert not orphans, f"volně stojící symboly: {orphans}"


def test_settings_buttons_have_uniform_width():
    from spillway import settings_window as sw

    css = sw._HTML[:sw._HTML.index("</style>")]
    # Popisky se za běhu mění („Změnit" → „5 s" → „Potvrdit"); bez pevné šířky
    # by řádek poskakoval.
    btn = css[css.index("  .btn{"):css.index("  .btn:disabled")]
    assert "min-width:112px" in btn and "text-align:center" in btn

    # Výzva „Stiskni klávesu…" patří k popisku, ne do tlačítka.
    assert "'Stiskni klávesu…'" in sw._HTML
    assert "Btn').textContent = 'Stiskni klávesu…'" not in sw._HTML


def test_help_links_point_at_existing_cards():
    import re

    from spillway import settings_window as sw

    html = sw._HTML
    # Odkazy z nápovědy musí mířit na kartu, která v nastavení opravdu je —
    # jinak uživatel skončí na začátku stránky a kartu hledá dole sám.
    targets = set(re.findall(r"showPage\('settings','([^']+)'\)", html))
    assert targets, "nápověda má odkazovat aspoň na jednu kartu"
    for t in targets:
        assert f'id="{t}"' in html, f"odkaz na neexistující kartu: {t}"


def test_destructive_actions_all_require_confirmation():
    from spillway import settings_window as sw

    html = sw._HTML
    # Každá nevratná akce musí projít pětisekundovým potvrzením — ať už je
    # tlačítko napojené přímo, nebo přes rozcestník (`keyAction`/`modelAction`).
    for action in ("reset_stats", "reset_history", "delkey", "model_remove"):
        assert f"armReset(this,'{action}')" in html or f"armReset(btn, '{action}')" in html, (
            f"{action} maže bez potvrzení"
        )


def test_parent_row_has_no_divider_above_its_suboption():
    from spillway import settings_window as sw

    css = sw._HTML[:sw._HTML.index("</style>")]
    # Čára mezi „Odesílání do AI modelu" a jeho podnastavením je vizuálně
    # oddělovala, i když patří k sobě.
    assert ".rowt:has(+ .rowt.sub){border-bottom:none;}" in css


def test_js_text_targets_are_not_parents_of_other_elements():
    import re

    from spillway import settings_window as sw

    html = sw._HTML
    # `el.textContent = ...` smaže VŠECHNY potomky. Když je cíl rodičem jiného
    # prvku s id, ten prvek zmizí a další zápis do něj spadne na null.
    # (Přesně tohle se stalo u karty modelu: `modelState` obaloval `modelHint`.)
    targets = set(re.findall(r"getElementById\('(\w+)'\)\.textContent\s*=", html))
    assert targets, "očekáváme aspoň jeden prvek, do kterého se píše text"

    for tid in targets:
        m = re.search(rf'<(\w+)[^>]*id="{tid}"[^>]*>(.*?)</\1>', html, re.S)
        if not m:
            continue  # samouzavírací nebo dynamicky vytvořený prvek
        assert 'id="' not in m.group(2), (
            f"prvek #{tid} obaluje další prvek s id — textContent by ho smazal"
        )


def test_model_card_offers_download_and_removal():
    from spillway import settings_window as sw

    html = sw._HTML
    # Model a API klíč jsou v JEDNÉ kartě — obojí je podmínka funkčnosti.
    for marker in ('id="cardSetup"', 'id="modelState"', 'id="modelHint"',
                   'id="modelProg"', "model_download", "model_remove"):
        assert marker in html, marker
    # Průběh stahování musí být vidět — 1,5 GB bez ukazatele vypadá jako zamrznutí.
    assert "applyModel" in html and "percent" in html


def test_hud_offers_download_when_model_missing():
    from spillway import hud

    # Bez modelu nemá okénko mlčet — přepis by spustil tiché stahování 1,5 GB
    # a vypadalo by to jako zamrznutí.
    html = hud._HTML if hasattr(hud, "_HTML") else hud.HTML
    assert "nomodel" in html and "Chybí model" in html
    assert ".dot.nomodel" in html, "výzva musí mít vlastní barvu tečky"


def test_clickable_hud_states_are_not_transparent_to_mouse():
    import inspect

    from spillway import hud

    # Na lístek i na výzvu se musí dát kliknout; u ostatních stavů má myš
    # propadávat do aplikace pod okénkem.
    src = inspect.getsource(hud)
    assert 'setIgnoresMouseEvents_(state not in ("ready", "nomodel"))' in src
    assert 'if state in ("ready", "nomodel") or at_icon:' in src


def test_setup_card_groups_key_and_model_together():
    from spillway import settings_window as sw

    html = sw._HTML
    # API klíč a model jsou obojí podmínka funkčnosti → jedna karta.
    setup = html[html.index('id="cardSetup"'):html.index('Data a soukromí')]
    assert "Model pro přepis" in setup and "Úprava textu přes Claude" in setup
    assert 'id="modelBtn"' in setup and 'id="keyBtn"' in setup and 'id="key"' in setup


def test_not_ready_banner_links_to_setup_card():
    from spillway import settings_window as sw

    html = sw._HTML
    assert 'id="notReady"' in html
    # Klik na pruh musí vést na kartu, která opravdu existuje.
    assert "showPage('settings','cardSetup')" in html
    assert 'id="cardSetup"' in html


def test_model_removal_goes_through_confirmation():
    from spillway import settings_window as sw

    html = sw._HTML
    # Mazání 1,5 GB je nevratné → stejné pětisekundové potvrzení jako u resetů.
    assert "armReset(btn, 'model_remove')" in html
    assert "btn.dataset.mode === 'remove'" in html


def test_welcome_explains_both_prerequisites():
    from spillway import settings_window as sw

    html = sw._HTML
    w = html[html.index('id="welcome"'):html.index("</div>", html.index('id="welcome"') + 200)]
    # Po instalaci musí být jasné, co je povinné a co ne.
    assert "Model pro přepis" in w and "nepojede" in w, "model = podmínka diktování"
    assert "API klíč" in w and "volitelný" in w, "klíč = volitelný, jen kvůli úpravě"
    # Ukáže se jen napoprvé.
    assert 'if(s.first_run) document.getElementById(\'welcome\').classList.remove' in html


def test_ai_options_are_locked_without_key():
    from spillway import settings_window as sw

    html = sw._HTML
    # Bez klíče nemá smysl nabízet odesílání do AI — musí zašednout a nejít zapnout.
    assert "function syncKey(has)" in html
    assert "classList.toggle('disabled', !has)" in html
    assert "classList.toggle('locked', !has)" in html
    # A dítě „Číst kontext pole" se řídí zamčeným rodičem.
    assert "!master.classList.contains('locked')" in html
