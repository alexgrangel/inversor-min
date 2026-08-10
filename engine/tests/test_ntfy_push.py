"""
Entrega por ntfy: lo testeable sin red (regla de tests de CLAUDE.md).

El transporte (_post) no se prueba; se prueba todo lo que decide QUÉ se
entrega: rehidratación desde notifications-latest.json, mapeo de prioridad,
codificación RFC 2047 de headers, y que el silencio y los suprimidos NO se
entregan.
"""
from __future__ import annotations

import json

import pytest

from inversor.notify import Notification
from inversor.notify_sinks import render_ntfy
from inversor.scripts import ntfy_push


def _aviso(**over) -> dict:
    base = dict(
        trigger="REGIME_FLIPPED",
        priority="MEDIUM",
        title="Régimen BTC: NEUTRAL → RISK_OFF",
        body="Cambió la etiqueta de régimen.",
        razonamiento=["BTC: régimen NEUTRAL → RISK_OFF."],
        estrategia=["No ejecutes por este aviso."],
        changed_from={"regime": "NEUTRAL"},
        changed_to={"regime": "RISK_OFF"},
        fired_at="2026-08-10T16:32:26+00:00",
        dedup_key="REGIME_FLIPPED:abc123",
        es_orden_ejecutable=False,
    )
    base.update(over)
    return base


def test_rehidratacion_desde_el_json_del_snapshot():
    payload = {"notifications": [_aviso()], "suppressed": [{"kind": "supresion"}]}
    ns = ntfy_push.rehidratar(payload)
    assert len(ns) == 1
    assert isinstance(ns[0], Notification)
    assert ns[0].trigger == "REGIME_FLIPPED"


def test_los_suprimidos_no_se_entregan():
    # "suppressed" es auditoría para la app; mandarlos al teléfono destruiría
    # exactamente el anti-spam que los suprimió.
    payload = {"notifications": [], "suppressed": [_aviso(), _aviso()]}
    assert ntfy_push.rehidratar(payload) == []


def test_mapeo_de_prioridad_a_ntfy():
    n_alta = Notification(**_aviso(priority="HIGH", trigger="BLOCKER_RAISED"))
    n_media = Notification(**_aviso(priority="MEDIUM"))
    n_info = Notification(**_aviso(priority="INFO", trigger="HURDLE_MOVED"))
    assert render_ntfy(n_alta, "t")["headers"]["Priority"] == "high"
    assert render_ntfy(n_media, "t")["headers"]["Priority"] == "default"
    assert render_ntfy(n_info, "t")["headers"]["Priority"] == "low"


def test_encode_header_ascii_pasa_intacto():
    assert ntfy_push.encode_header("Fee budget low") == "Fee budget low"


def test_encode_header_utf8_va_en_rfc2047():
    # Los títulos reales traen flechas y acentos; urllib codifica headers como
    # latin-1 y "→" lo truena. RFC 2047 con base64 lo transporta intacto.
    codificado = ntfy_push.encode_header("Régimen BTC: NEUTRAL → RISK_OFF")
    assert codificado.startswith("=?UTF-8?B?") and codificado.endswith("?=")
    import base64

    dentro = codificado[len("=?UTF-8?B?"):-2]
    assert base64.b64decode(dentro).decode("utf-8") == "Régimen BTC: NEUTRAL → RISK_OFF"


def test_sin_topic_omite_la_entrega_sin_fallar(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setattr(
        ntfy_push, "_post", lambda p: (_ for _ in ()).throw(AssertionError("no debió mandar"))
    )
    f = tmp_path / "notifications-latest.json"
    f.write_text(json.dumps({"notifications": [_aviso()]}))
    assert ntfy_push.main(["ntfy_push", str(f)]) == 0
    assert "omitida" in capsys.readouterr().out


def test_cero_avisos_no_manda_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "topic-de-prueba")
    monkeypatch.setattr(
        ntfy_push, "_post", lambda p: (_ for _ in ()).throw(AssertionError("no debió mandar"))
    )
    f = tmp_path / "notifications-latest.json"
    f.write_text(json.dumps({"notifications": [], "suppressed": []}))
    assert ntfy_push.main(["ntfy_push", str(f)]) == 0


def test_entrega_postea_una_vez_por_aviso_al_topic(tmp_path, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "topic-secreto")
    mandados: list[dict] = []

    def post_falso(p):
        mandados.append(p)
        return 200

    monkeypatch.setattr(ntfy_push, "_post", post_falso)
    f = tmp_path / "notifications-latest.json"
    f.write_text(
        json.dumps({"notifications": [_aviso(), _aviso(priority="HIGH", trigger="BLOCKER_RAISED")]})
    )
    assert ntfy_push.main(["ntfy_push", str(f)]) == 0
    assert len(mandados) == 2
    assert all(p["url"] == "https://ntfy.sh/topic-secreto" for p in mandados)


def test_un_aviso_caido_tras_reintentos_no_calla_al_resto(tmp_path, monkeypatch):
    # Se parcha `entregar` (no `_post`): un fallo transitorio de _post lo
    # salvan los reintentos; lo que este test pinnea es que un aviso caído
    # DEFINITIVAMENTE no impide intentar los siguientes, y el exit es 1.
    monkeypatch.setenv("NTFY_TOPIC", "t")
    entregados: list[str] = []

    def entregar_a_veces(p):
        entregados.append(p["headers"]["Title"])
        if len(entregados) == 1:
            raise OSError("caído tras agotar reintentos")
        return 200

    monkeypatch.setattr(ntfy_push, "entregar", entregar_a_veces)
    f = tmp_path / "notifications-latest.json"
    f.write_text(json.dumps({"notifications": [_aviso(), _aviso()]}))
    assert ntfy_push.main(["ntfy_push", str(f)]) == 1
    assert len(entregados) == 2  # el segundo sí se intentó


def test_archivo_inexistente_es_benigno(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    assert ntfy_push.main(["ntfy_push", "/no/existe.json"]) == 0


def test_un_archivo_rancio_no_se_reentrega(tmp_path, monkeypatch):
    # El bug que motivó esto: un job verde sin correr el engine dejaba el
    # notifications-latest.json de la corrida ANTERIOR en el árbol, y el paso
    # de ntfy re-posteaba los avisos de ayer. Un archivo de >24h no se entrega
    # y el paso sale rojo para que se investigue.
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setattr(
        ntfy_push, "_post", lambda p: (_ for _ in ()).throw(AssertionError("no debió mandar"))
    )
    ayer = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    f = tmp_path / "notifications-latest.json"
    f.write_text(json.dumps({"generated_at": ayer, "notifications": [_aviso()]}))
    assert ntfy_push.main(["ntfy_push", str(f)]) == 1


def test_un_archivo_fresco_si_se_entrega(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setenv("NTFY_TOPIC", "t")
    mandados: list[dict] = []
    monkeypatch.setattr(ntfy_push, "_post", lambda p: mandados.append(p) or 200)
    f = tmp_path / "notifications-latest.json"
    f.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "notifications": [_aviso()],
            }
        )
    )
    assert ntfy_push.main(["ntfy_push", str(f)]) == 0
    assert len(mandados) == 1


def test_entregar_reintenta_con_backoff_y_luego_pega(monkeypatch):
    intentos: list[int] = []
    esperas: list[float] = []

    def post_flaky(p):
        intentos.append(1)
        if len(intentos) < 3:
            raise OSError("timeout")
        return 200

    monkeypatch.setattr(ntfy_push, "_post", post_flaky)
    monkeypatch.setattr(ntfy_push.time, "sleep", lambda s: esperas.append(s))
    assert ntfy_push.entregar({"url": "u", "body": "b", "headers": {}}) == 200
    assert len(intentos) == 3
    assert esperas == list(ntfy_push.REINTENTOS_BACKOFF_S)


def test_entregar_se_rinde_despues_de_agotar_reintentos(monkeypatch):
    monkeypatch.setattr(
        ntfy_push, "_post", lambda p: (_ for _ in ()).throw(OSError("caído"))
    )
    monkeypatch.setattr(ntfy_push.time, "sleep", lambda s: None)
    with pytest.raises(OSError):
        ntfy_push.entregar({"url": "u", "body": "b", "headers": {}})


def test_exit_blocked_no_colisiona_con_codigos_reservados():
    # argparse sale con 2 en errores de uso; 1 es fallo genérico; 64 es el
    # usage del pusher; 126-128+ son del shell. Si EXIT_BLOCKED cae en uno de
    # ésos, el workflow no puede distinguir "decisión bloqueada: publícala"
    # de "el CLI ni siquiera corrió" — fue un bug real con el 2.
    from inversor.__main__ import EXIT_BLOCKED

    assert EXIT_BLOCKED not in (0, 1, 2, 64, 126, 127, 128, 130)
