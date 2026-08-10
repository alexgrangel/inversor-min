"""
Corrida offline con los datos macro REALES de agosto 2026 y una serie cripto
SINTÉTICA (vol 45% anualizada, tendencia alcista suave).

Sirve para dos cosas: ver la forma de la salida sin token de Banxico, y validar
que la aritmética del hurdle, comisiones e impuestos —que es la parte que no
depende de la serie cripto— da lo que debe dar.

    python -m inversor.scripts.demo_offline
"""
from __future__ import annotations

import math
import random
from datetime import date

from ..config import Policy, Portfolio
from ..decide import decide
from ..report import to_markdown
from ..sources.banxico import Observation

# Datos verificados (subasta CETES 4-ago-2026, FIX 7-ago-2026, Banxico 6-ago-2026)
REAL = {
    "fix_usdmxn": 17.1387,
    "cetes_28": 6.17,
    "cetes_91": 6.40,
    "cetes_182": 6.75,
    "cetes_364": 7.01,
    "tasa_objetivo": 6.50,
    "inpc_anual": 3.12,  # INPC general anual, julio 2026 (INEGI). Subyacente: 3.95%
}


def synth_crypto(n=500, annual_vol=0.45, annual_drift=0.35, seed=11):
    rng = random.Random(seed)
    dv, dd = annual_vol / math.sqrt(365), annual_drift / 365
    p, out = 60_000.0, []
    for _ in range(n):
        p *= math.exp(dd - 0.5 * dv**2 + rng.gauss(0, dv))
        out.append(p)
    return out


def main() -> int:
    today = date(2026, 8, 10)
    obs = {k: Observation(k, "REAL", v, date(2026, 8, 7), 3) for k, v in REAL.items()}
    closes = {
        "BTC": synth_crypto(annual_vol=0.45, seed=11),
        "ETH": synth_crypto(annual_vol=0.60, seed=12),
    }
    policy = Policy(
        portfolio=Portfolio(total_capital_mxn=50_000.0, horizon_days=364,
                            liquidity_reserve_mxn=5_000.0)
    )
    d = decide(policy, obs, closes, current_crypto_mxn=0.0, today=today)
    print(to_markdown(d))
    print("\n> Serie cripto SINTÉTICA. El bloque macro/fiscal/comisiones usa datos reales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
