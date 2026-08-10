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


def test_un_post_caido_no_calla_al_resto_y_sale_distinto_de_cero(tmp_path, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    intentos: list[str] = []

    def post_a_veces(p):
        intentos.append(p["headers"]["Title"])
        if len(intentos) == 1:
            raise OSError("timeout")
        return 200

    monkeypatch.setattr(ntfy_push, "_post", post_a_veces)
    f = tmp_path / "notifications-latest.json"
    f.write_text(json.dumps({"notifications": [_aviso(), _aviso()]}))
    assert ntfy_push.main(["ntfy_push", str(f)]) == 1
    assert len(intentos) == 2  # el segundo sí se intentó


def test_archivo_inexistente_es_benigno(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    assert ntfy_push.main(["ntfy_push", "/no/existe.json"]) == 0
