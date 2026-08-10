from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .decide import Decision

ACTION_ES = {
    "STAY_IN_CETES": "Quedarse en CETES",
    "ALLOCATE_TO_CRYPTO": "Aumentar sleeve cripto",
    "REDUCE_CRYPTO": "Reducir sleeve cripto",
    "HOLD_NO_ACTION": "Sin acción",
    "BLOCKED_FEE_BUDGET": "Bloqueado: presupuesto de comisiones agotado",
    "BLOCKED_STALE_DATA": "Bloqueado: datos rancios",
    "BLOCKED_BELOW_MIN_NOTIONAL": "Bloqueado: por debajo del mínimo operable",
}


def write_snapshot(d: Decision, out_dir: Path, today: date | None = None) -> tuple[Path, Path]:
    """
    Escribe el snapshot del día y actualiza latest.json.

    El directorio de snapshots ES el log walk-forward. Cada corrida queda
    versionada en git con timestamp inmutable. Eso es lo que después permite
    contestar la única pregunta que importa: ¿este sistema le ganó a CETES
    fuera de muestra? Sin este log, en seis meses no vas a poder distinguir
    entre que funcionó y que te acuerdas de que funcionó.
    """
    today = today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = d.to_json_dict()
    dated = out_dir / f"{today:%Y-%m-%d}.json"
    latest = out_dir / "latest.json"
    for p in (dated, latest):
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dated, latest


def to_markdown(d: Decision) -> str:
    L: list[str] = []
    L.append(f"# {ACTION_ES.get(d.action, d.action)}")
    L.append("")
    L.append(f"**{d.headline}**")
    L.append("")
    L.append(f"_Generado: {d.generated_at} · schema {d.schema_version}_")
    L.append("")

    if d.blockers:
        L.append("## Bloqueos")
        L += [f"- {b}" for b in d.blockers]
        L.append("")

    h = d.hurdle
    if h:
        L.append("## Costo de oportunidad")
        L.append("")
        L.append("| Concepto | Valor |")
        L.append("|---|---|")
        L.append(f"| CETES {h['tenor_days']}d nominal (anual) | {h['cetes_nominal']:.2%} |")
        L.append(f"| Inflación anual | {h['inflacion']:.2%} |")
        L.append(f"| Interés real (Fisher) | {h['cetes_real_pretax']:.2%} |")
        L.append(f"| Base gravable LISR 134 (resta) | {h['base_gravable_lisr134']:.2%} |")
        L.append(f"| ISR sobre esa base | −{h['isr_sobre_interes_real']:.2%} |")
        L.append(f"| **CETES neto nominal (anual)** | **{h['cetes_neto_nominal']:.2%}** |")
        L.append(f"| CETES neto real | {h['cetes_neto_real']:.2%} |")
        L.append(f"| Prima de riesgo exigida | {h['prima_de_riesgo_exigida']:.2%} |")
        L.append(f"| **Hurdle anualizado** | **{h['hurdle_total_anualizado']:.2%}** |")
        L.append(
            f"| **Hurdle en tu horizonte ({h['horizon_days']}d)** |"
            f" **{h['hurdle_total_periodo']:.2%}** |"
        )
        L.append("")

    if d.allocation_mxn:
        L.append("## Asignación objetivo")
        L.append("")
        L.append("| Instrumento | MXN |")
        L.append("|---|---:|")
        for k, v in d.allocation_mxn.items():
            L.append(f"| {k} | {v:,.0f} |")
        L.append("")

    c = d.costs
    if c:
        L.append("## Presupuesto de comisiones")
        L.append("")
        L.append(f"- Operaciones completas permitidas al año: **{c['max_round_trips_per_year']:.1f}**")
        L.append(f"- Restantes: **{c['round_trips_remaining']:.1f}**")
        L.append(f"- Movimiento mínimo para no perder por comisiones: **{c['breakeven_move_pct']:.2%}**")
        L.append("")

    m = d.sizing.get("materiality")
    if m:
        L.append("## ¿Mueve la aguja?")
        L.append("")
        L.append(f"Sleeve = **{m['peso_sobre_capital_total']:.1%}** del capital total · veredicto **{m['veredicto']}**")
        L.append("")
        L.append("| Si cripto hace… | Impacto en el portafolio | En pesos |")
        L.append("|---|---:|---:|")
        for s in m["escenarios"]:
            L.append(
                f"| {s['movimiento_cripto']:+.0%} | {s['impacto_portafolio_pct']:+.2%}"
                f" | {s['impacto_portafolio_mxn']:+,.0f} MXN |"
            )
        L.append("")
        L.append(f"Contra eso: CETES te paga **{m['cetes_anual_mxn']:,.0f} MXN** al año, neto, sin volatilidad.")
        L.append("")

    if d.required_returns:
        L.append("## Qué tan grande es la apuesta implícita")
        L.append("")
        L.append(f"> {d.required_returns['explicacion']}")
        L.append("")

    if d.fx.get("sensibilidad"):
        L.append("### Sensibilidad al tipo de cambio")
        L.append("")
        L.append("| Movimiento MXN | Rendimiento USD requerido |")
        L.append("|---|---:|")
        for s in d.fx["sensibilidad"]:
            L.append(f"| {s['escenario_mxn']:+.0%} | {s['rendimiento_usd_requerido']:.2%} |")
        L.append("")

    if d.reasons:
        L.append("## Razonamiento")
        L += [f"- {r}" for r in d.reasons]
        L.append("")

    if d.warnings:
        L.append("## Advertencias")
        L += [f"- ⚠️ {w}" for w in d.warnings]
        L.append("")

    L.append("---")
    L.append("")
    L.append(
        "_Este sistema no pronostica precios. Dimensiona riesgo, impone un techo de"
        " comisiones y compara contra CETES neto de impuestos. Uso personal. No es"
        " asesoría en inversiones._"
    )
    return "\n".join(L)
