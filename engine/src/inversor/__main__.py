"""
CLI. Uso:

    BANXICO_TOKEN=... python -m inversor run --capital 50000 --held 0
    BANXICO_TOKEN=... python -m inversor run --dry-run       # sin escribir snapshot
    BANXICO_TOKEN=... python -m inversor run --no-notify     # sin paso de avisos
    BANXICO_TOKEN=... python -m inversor run --notify-dry-run  # avisos sin persistir
    python -m inversor verify-series
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from .config import CostPolicy, Policy, Portfolio, TaxPolicy
from .decide import Decision, decide
from .notify import NotifyPolicy, evaluate_with_audit
from .notify_sinks import render_markdown
from .report import to_markdown, write_snapshot
from .sources import banxico as bx
from .sources import market_data as md

BANXICO_KEYS = [
    "fix_usdmxn",
    "cetes_28",
    "cetes_91",
    "cetes_182",
    "cetes_364",
    "tasa_objetivo",
    "inpc_anual",
]

NOTIFY_HISTORY = "notifications.json"
NOTIFY_LATEST = "notifications-latest.json"


def _load_previous_decision(out_dir: Path, current: Decision) -> Decision | None:
    """
    Lee `latest.json` ANTES de sobrescribirlo. Es la única memoria del día previo.

    Si el schema mayor cambió, la comparación campo a campo ya no significa lo
    mismo y devolver algo sería inventar un cambio de estado. Devolver None
    equivale a "primera corrida": silencio, con aviso explícito en stderr. Nunca
    se degrada en silencio (regla 4).
    """
    p = out_dir / "latest.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    mayor_previo = str(data.get("schema_version", "")).split(".")[0]
    mayor_actual = current.schema_version.split(".")[0]
    if mayor_previo != mayor_actual:
        print(
            f"[notify] schema {data.get('schema_version')} ≠ {current.schema_version}:"
            " el snapshot previo no es comparable. Sin notificaciones hoy.",
            file=sys.stderr,
        )
        return None
    # Campos ADITIVOS con el mismo mayor son parte del contrato de CLAUDE.md
    # ("campos nuevos: permitidos sin subir versión mayor"), así que se ignoran
    # con nota en stderr en vez de tronar. `Decision(**data)` a secas mataba la
    # corrida completa del cron por un campo que el contrato permite agregar.
    conocidos = {f.name for f in fields(Decision)}
    extras = sorted(set(data) - conocidos)
    if extras:
        print(
            f"[notify] el snapshot previo trae campos que este engine no conoce"
            f" ({', '.join(extras)}). Se ignoran: son aditivos y el mayor no cambió.",
            file=sys.stderr,
        )
    faltantes = sorted(conocidos - set(data))
    if faltantes:
        # Al revés no: un campo que YA no viene cambia el significado de la
        # comparación campo a campo y eso exige subir el mayor. Truena fuerte.
        raise ValueError(
            f"El snapshot previo no trae {faltantes} con el mismo schema mayor"
            f" ({data.get('schema_version')}). Quitar campos exige subir SCHEMA_VERSION."
        )
    return Decision(**{k: v for k, v in data.items() if k in conocidos})


def _load_history(out_dir: Path) -> list[dict[str, Any]]:
    p = out_dir / NOTIFY_HISTORY
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{p} debe ser una lista append-only de registros.")
    return data


def cmd_notify_step(
    d: Decision, out_dir: Path, previous: Decision | None, persistir: bool
) -> None:
    """
    Paso de notificación: evalúa cambios de estado y persiste el log.

    `notifications.json` es append-only por la misma razón que `snapshots/`
    (regla 3): además de log, es la memoria de cooldowns e histéresis entre
    corridas del cron. Reescribirlo borra el estado del anti-spam.
    """
    history = _load_history(out_dir)
    ns, auditoria = evaluate_with_audit(d, previous, history, NotifyPolicy(), d.costs)
    print(render_markdown(ns))

    if not persistir:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    history.extend([n.to_record() for n in ns])
    history.extend(auditoria)
    (out_dir / NOTIFY_HISTORY).write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / NOTIFY_LATEST).write_text(
        json.dumps(
            {
                "generated_at": d.generated_at,
                "schema_version": d.schema_version,
                "notifications": [n.to_dict() for n in ns],
                "suppressed": [r for r in auditoria if r.get("kind") == "supresion"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_policy(args: argparse.Namespace) -> Policy:
    p = Policy()
    p = replace(
        p,
        portfolio=Portfolio(
            total_capital_mxn=args.capital,
            horizon_days=args.horizon,
            liquidity_reserve_mxn=args.reserve,
        ),
        tax=TaxPolicy(
            marginal_isr_rate=args.isr,
            ganancias_cripto_ytd_mxn=args.crypto_gains_ytd,
        ),
        cost=CostPolicy(fees_spent_ytd_mxn=args.fees_ytd),
    )
    return p


def cmd_run(args: argparse.Namespace) -> int:
    policy = build_policy(args)
    token = bx.get_token()

    obs = bx.fetch_latest(BANXICO_KEYS, token)
    # Los timestamps ya NO se descartan: decide() los usa para bloquear por
    # precios rancios, y el venue que sirvió cada serie va al snapshot para que
    # un cambio de fuente sea visible en el log walk-forward.
    series: dict[str, list[tuple[Any, float]]] = {}
    venues: dict[str, str] = {}
    for s in policy.universe.crypto_symbols:
        serie, venue, fallos = md.daily_closes(
            s, limit=500, orden=policy.universe.venue_order
        )
        series[s], venues[s] = serie, venue
        if fallos:
            print(f"[market_data] {s}: usando {venue}. Fallaron: {'; '.join(fallos)}",
                  file=sys.stderr)

    closes = {s: [c for _, c in v] for s, v in series.items()}
    closes_as_of = {s: v[-1][0] for s, v in series.items()}

    d = decide(
        policy, obs, closes,
        current_crypto_mxn=args.held,
        closes_as_of=closes_as_of,
        venues=venues,
    )
    reporte = to_markdown(d)   # no reusar el nombre `md`: es el módulo market_data
    print(reporte)

    out = Path(args.out).resolve()
    # El snapshot previo se lee AQUÍ: write_snapshot pisa latest.json y con él
    # se perdería el único punto de comparación del día anterior.
    previous = _load_previous_decision(out, d) if not args.no_notify else None

    if not args.dry_run:
        dated, latest = write_snapshot(d, out)
        (out / "latest.md").write_text(reporte, encoding="utf-8")
        print(f"\n→ {dated}\n→ {latest}", file=sys.stderr)

    if not args.no_notify:
        print("")
        cmd_notify_step(
            d, out, previous, persistir=not (args.dry_run or args.notify_dry_run)
        )

    return 0 if not d.blockers else 2


def cmd_verify(_: argparse.Namespace) -> int:
    """
    Confirma que cada ID de serie devuelve lo que creemos que devuelve.

    Ya no es sólo informativo: valida el título oficial contra
    TITULO_DEBE_CONTENER / TITULO_NO_DEBE_CONTENER y sale con código != 0 si
    algo no corresponde, para que un ID equivocado truene en CI en vez de
    depender de que un humano lea la lista con atención.
    """
    token = bx.get_token()
    ok = True
    for key, sid in bx.SERIES.items():
        try:
            payload = bx._request(f"/series/{sid}", token)
            title = payload["bmx"]["series"][0].get("titulo", "?")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  ✗ {key:16s} {sid:10s} → ERROR: {e}")
            continue
        problemas = bx.validate_series_title(key, title)
        lo, hi = bx.SANITY[key]
        marca = "✓" if not problemas else "✗"
        print(f"  {marca} {key:16s} {sid:10s} → {title}")
        print(f"  {'':18s} {'':10s}   rango esperado [{lo}, {hi}]")
        for p in problemas:
            ok = False
            print(f"  {'':18s} {'':10s}   ⚠ {p}")
    if ok:
        print("\nTodos los títulos son consistentes con lo que cada llave dice ser.")
    else:
        print("\nHay series que NO corresponden. Corrige SERIES en sources/banxico.py.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="inversor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Genera la decisión del día")
    r.add_argument("--capital", type=float, default=50_000.0)
    r.add_argument("--reserve", type=float, default=5_000.0)
    r.add_argument("--horizon", type=int, default=364)
    r.add_argument("--isr", type=float, default=0.30, help="Tasa marginal de ISR")
    r.add_argument("--held", type=float, default=0.0, help="Sleeve cripto actual en MXN")
    r.add_argument("--fees-ytd", type=float, default=0.0)
    r.add_argument("--crypto-gains-ytd", type=float, default=0.0)
    r.add_argument("--out", default="../snapshots")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument(
        "--no-notify", action="store_true", help="No evalúa cambios de estado ni avisa"
    )
    r.add_argument(
        "--notify-dry-run",
        action="store_true",
        help="Evalúa e imprime los avisos, pero no toca notifications.json",
    )
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("verify-series", help="Valida IDs de serie de Banxico")
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
