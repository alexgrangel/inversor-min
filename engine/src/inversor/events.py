"""
Calendario de eventos CONOCIDOS y programados, con escenarios pre-computados.

Esta es la sustitución honesta de las "alertas de noticias en tiempo real".
No puedes predecir qué va a hacer Banxico; sí sabes exactamente CUÁNDO lo va a
hacer, y puedes calcular de antemano qué le hace cada resultado posible a tu
hurdle. Lo primero es un dato; lo segundo es aritmética. Ninguno de los dos es
un pronóstico, y por eso este módulo no viola la regla 1 de CLAUDE.md.

El valor no está en la lista de fechas: está en `escenarios_banxico`. Llegar al
24 de septiembre sabiendo que un recorte de 25 pb mueve tu hurdle X y tu sleeve
objetivo Y es lo contrario de reaccionar al encabezado del día siguiente.

⚠️ PROCEDENCIA DE LAS FECHAS (CLAUDE.md regla 5: nada se inventa, todo se
   marca). NO HAY FUENTE MACHINE-READABLE para ninguna de estas listas:

  BANXICO 2026   DERIVADO, no leído limpio de una máquina. Banxico publica su
                 calendario en PDF y nada más. Las tres fechas restantes
                 (24-sep, 5-nov, 17-dic) salen de cruzar ese PDF contra el
                 índice de anuncios publicados: 5-feb, 26-mar, 7-may, 25-jun y
                 6-ago ya ocurrieron. Es una derivación humana; trátala como
                 dato de segunda mano y reverifícala contra el PDF antes de
                 apoyar una decisión grande en ella.
  BANXICO 2027   NO PUBLICADO todavía. El código NO extrapola: cuando la
                 ventana pedida rebasa la cobertura, emite un aviso explícito
                 (tipo CALENDARIO_AGOTADO). Inventar "el tercer jueves de cada
                 trimestre" produciría fechas equivocadas con cara de dato.
  FOMC           Del calendario oficial de la Fed (2026 y 2027 publicados).
  CPI EE.UU.     Del calendario de releases del BLS, 2026.
  SUBASTA CETES  GENERADA, no hardcodeada: martes de subasta, colocación el
                 jueves. Los días festivos la recorren y aquí NO hay calendario
                 de festivos, así que va marcada como no verificada.
  INPC INEGI     Regla "≈ día 9 de cada mes" SIN VERIFICAR. Va marcada.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .config import Policy
from .sources.banxico import pick_hurdle_tenor
from .tax import annualized_to_period, hurdle_rate

# --- Fechas duras. Ver el bloque de PROCEDENCIA en el docstring del módulo. ---

# DERIVADAS (PDF oficial × índice de anuncios). Reverificar contra el PDF.
BANXICO_2026: tuple[date, ...] = (
    date(2026, 9, 24),
    date(2026, 11, 5),
    date(2026, 12, 17),
)
# Última fecha que el calendario de Banxico cubre. Más allá: aviso, no invento.
BANXICO_COBERTURA_HASTA = date(2026, 12, 31)

# FOMC: reuniones de dos días. Se guarda (inicio, fin); el anuncio es el 2º día.
FOMC: tuple[tuple[date, date], ...] = (
    (date(2026, 9, 15), date(2026, 9, 16)),
    (date(2026, 10, 27), date(2026, 10, 28)),
    (date(2026, 12, 8), date(2026, 12, 9)),
    (date(2027, 1, 26), date(2027, 1, 27)),
    (date(2027, 3, 16), date(2027, 3, 17)),
    (date(2027, 4, 27), date(2027, 4, 28)),
    (date(2027, 6, 8), date(2027, 6, 9)),
    (date(2027, 7, 27), date(2027, 7, 28)),
    (date(2027, 9, 14), date(2027, 9, 15)),
    (date(2027, 10, 26), date(2027, 10, 27)),
    (date(2027, 12, 7), date(2027, 12, 8)),
)
FOMC_COBERTURA_HASTA = date(2027, 12, 31)

CPI_US_2026: tuple[date, ...] = (
    date(2026, 8, 12),
    date(2026, 9, 11),
    date(2026, 10, 14),
    date(2026, 11, 10),
    date(2026, 12, 10),
)
CPI_US_COBERTURA_HASTA = date(2026, 12, 31)

# Subasta primaria de CETES: martes. La colocación (liquidación) cae el jueves.
DIA_SUBASTA_CETES = 1  # 0 = lunes en date.weekday()
DIAS_A_COLOCACION = 2
# INPC de INEGI: ≈ día 9. REGLA SIN VERIFICAR contra el calendario de INEGI.
DIA_INPC = 9

# Resultados de política monetaria para los que se pre-computa el escenario.
# No llevan probabilidad asociada A PROPÓSITO: ponerle una probabilidad a cada
# uno sería un pronóstico, y este repo no pronostica (CLAUDE.md regla 1).
MOVIMIENTOS_BANXICO: tuple[tuple[int, str], ...] = (
    (-50, "recorte de 50 pb"),
    (-25, "recorte de 25 pb"),
    (0, "sin cambio"),
    (25, "alza de 25 pb"),
)

SUPUESTOS_ESCENARIOS: tuple[str, ...] = (
    "SUPUESTO, NO PRONÓSTICO: la curva de CETES se desplaza en PARALELO por el"
    " mismo número de puntos base que la tasa objetivo. En la práctica la curva"
    " empina o aplana y los plazos largos suelen moverse menos que el corto;"
    " este escenario NO modela eso.",
    "SUPUESTO: la inflación anual se queda donde está. El hurdle depende de ella"
    " vía la base gravable de LISR art. 134, así que un escenario con inflación"
    " distinta da otro número.",
    "Esta tabla NO asigna probabilidades a los resultados ni dice cuál va a"
    " ocurrir. Sólo responde 'si pasa X, mi hurdle queda en Y'.",
    "El sleeve objetivo aquí es el que permite el presupuesto de riesgo a esa"
    " tasa. Sigue sujeto al multiplicador de régimen, al de señales (≤ 1.0) y a"
    " todos los bloqueos de decide.py.",
)


@dataclass(frozen=True)
class Event:
    fecha: date
    tipo: str
    nombre: str
    fuente: str
    verificado: bool
    fecha_fin: date | None = None
    nota: str = ""


@dataclass(frozen=True)
class EscenarioBanxico:
    movimiento_bp: int
    etiqueta: str
    tenor_days: int
    cetes_nominal: float
    cetes_neto_nominal: float
    hurdle_anualizado: float
    hurdle_periodo: float
    delta_hurdle_bp: float
    peso_objetivo: float
    sleeve_objetivo_mxn: float
    delta_sleeve_mxn: float
    restriccion: str
    supuestos: tuple[str, ...]


# ------------------------------------------------------------------ calendario

def _entre(f: date, desde: date, hasta: date) -> bool:
    return desde <= f <= hasta


def _subastas_cetes(desde: date, hasta: date) -> list[Event]:
    """
    Se generan, no se hardcodean: es una regla semanal estable y una lista
    manual de 52 fechas al año sólo agrega superficie para equivocarse.
    """
    out: list[Event] = []
    f = desde + timedelta(days=(DIA_SUBASTA_CETES - desde.weekday()) % 7)
    while f <= hasta:
        out.append(
            Event(
                fecha=f,
                tipo="SUBASTA_CETES",
                nombre="Subasta primaria de CETES",
                fuente="regla semanal (Banxico)",
                verificado=False,
                nota=(
                    f"Colocación el {f + timedelta(days=DIAS_A_COLOCACION):%d-%b}."
                    " SIN VERIFICAR: los días festivos recorren la subasta y este"
                    " módulo no tiene calendario de festivos."
                ),
            )
        )
        f += timedelta(days=7)
    return out


def _publicaciones_inpc(desde: date, hasta: date) -> list[Event]:
    out: list[Event] = []
    y, m = desde.year, desde.month
    while date(y, m, 1) <= hasta:
        f = date(y, m, DIA_INPC)
        if _entre(f, desde, hasta):
            out.append(
                Event(
                    fecha=f,
                    tipo="INPC",
                    nombre="Publicación de INPC (INEGI)",
                    fuente="regla mensual",
                    verificado=False,
                    nota=(
                        f"REGLA SIN VERIFICAR: se asume día {DIA_INPC} de cada mes."
                        " Confírmala contra el calendario de difusión de INEGI antes"
                        " de usarla para algo que no sea 'ojo, viene el dato'."
                    ),
                )
            )
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _avisos_cobertura(desde: date, hasta: date) -> list[Event]:
    """
    Cuando la ventana rebasa lo que el calendario duro cubre, se emite un aviso
    explícito en vez de devolver una lista vacía que se lee como "no viene nada".

    Silencio y ausencia de eventos son indistinguibles para quien consume la
    lista, y esa ambigüedad es justo la que causa que alguien opere el día de
    una decisión de tasa creyendo que no había nada en el calendario.
    """
    fuentes = (
        ("BANXICO", BANXICO_COBERTURA_HASTA, "calendario de Banxico (PDF, anual)"),
        ("FOMC", FOMC_COBERTURA_HASTA, "calendario del FOMC"),
        ("CPI_US", CPI_US_COBERTURA_HASTA, "calendario de releases del BLS"),
    )
    out: list[Event] = []
    for tipo, cubre_hasta, fuente in fuentes:
        if hasta <= cubre_hasta:
            continue
        primer_dia_sin_cubrir = max(cubre_hasta + timedelta(days=1), desde)
        out.append(
            Event(
                fecha=primer_dia_sin_cubrir,
                tipo="CALENDARIO_AGOTADO",
                nombre=f"Calendario {tipo} agotado el {cubre_hasta.isoformat()}",
                fuente=fuente,
                verificado=True,
                nota=(
                    f"La ventana pedida llega al {hasta.isoformat()} y el calendario"
                    f" duro de {tipo} sólo cubre hasta {cubre_hasta.isoformat()}."
                    " NO se extrapolan fechas: actualiza la lista desde la fuente"
                    " oficial. Faltan eventos, no es que no haya."
                ),
            )
        )
    return out


def proximos_eventos(today: date | None = None, dias: int = 30) -> list[Event]:
    """
    Eventos programados en [today, today + dias], ordenados por fecha.

    Incluye avisos de tipo CALENDARIO_AGOTADO cuando la ventana rebasa lo que
    las listas duras cubren. Un aviso NO es un evento con fecha inventada: su
    fecha es el primer día sin cubrir y su `tipo` lo hace imposible de confundir.
    """
    if dias < 0:
        raise ValueError("dias no puede ser negativo.")
    today = today or date.today()
    hasta = today + timedelta(days=dias)

    out: list[Event] = []
    for f in BANXICO_2026:
        if _entre(f, today, hasta):
            out.append(
                Event(
                    fecha=f,
                    tipo="BANXICO",
                    nombre="Decisión de política monetaria de Banxico",
                    fuente="calendario oficial (PDF) × índice de anuncios",
                    verificado=False,
                    nota=(
                        "Fecha DERIVADA, no leída de una fuente machine-readable."
                        " Reverifícala contra el PDF de Banxico."
                    ),
                )
            )
    for inicio, fin in FOMC:
        if _entre(inicio, today, hasta) or _entre(fin, today, hasta):
            out.append(
                Event(
                    fecha=inicio,
                    fecha_fin=fin,
                    tipo="FOMC",
                    nombre="Reunión del FOMC",
                    fuente="calendario oficial de la Reserva Federal",
                    verificado=True,
                    nota=f"El comunicado sale el segundo día ({fin.isoformat()}).",
                )
            )
    for f in CPI_US_2026:
        if _entre(f, today, hasta):
            out.append(
                Event(
                    fecha=f,
                    tipo="CPI_US",
                    nombre="Publicación de CPI de EE. UU.",
                    fuente="calendario de releases del BLS",
                    verificado=True,
                )
            )

    out.extend(_subastas_cetes(today, hasta))
    out.extend(_publicaciones_inpc(today, hasta))
    out.extend(_avisos_cobertura(today, hasta))

    # Los avisos al final dentro del mismo día: son metadatos, no eventos.
    return sorted(out, key=lambda e: (e.fecha, e.tipo == "CALENDARIO_AGOTADO", e.tipo))


def cobertura_calendario(today: date | None = None, dias: int = 30) -> tuple[bool, list[str]]:
    """(completa, faltantes). Azúcar para quien no quiera filtrar los avisos."""
    today = today or date.today()
    avisos = _avisos_cobertura(today, today + timedelta(days=dias))
    return (not avisos), [a.nota for a in avisos]


# ------------------------------------------------------- escenarios de Banxico

def _sleeve_objetivo(
    policy: Policy,
    cetes_neto_nominal: float,
    vol_annual: float | None,
    multiplicador: float,
) -> tuple[float, float, str]:
    """
    Peso objetivo del sleeve a una tasa dada. Devuelve (peso, MXN, restricción).

    NO se llama a `risk.size_crypto_sleeve` directamente por dos razones, ambas
    deliberadas: (1) esa función no sabe expresar "sin restricción de vol", que
    es el caso cuando el llamador no trae la vol realizada a la mano, y
    (2) su `assumed_asset_dd` es insensible a la tasa, y aquí el punto entero es
    la sensibilidad a la tasa. Las tres restricciones son las MISMAS que en
    risk.py y cualquier cambio allá tiene que reflejarse aquí.

    La única diferencia de fondo: al presupuesto de caída se le suma el COSTO DE
    OPORTUNIDAD. Tener el sleeve un año no sólo arriesga `assumed_asset_dd`;
    también renuncia al rendimiento CETES neto sobre ese mismo dinero. Cuando la
    tasa libre de riesgo sube, tener cripto cuesta más aunque cripto no se mueva,
    y el presupuesto alcanza para menos. Es una restricción MÁS estricta que la
    de risk.py, nunca más laxa: nadie termina con más posición por pasar por aquí.
    """
    r = policy.risk
    denominador = r.assumed_crypto_max_drawdown + max(cetes_neto_nominal, 0.0)
    candidatos: dict[str, float] = {
        "drawdown_budget_con_costo_de_oportunidad": (
            r.max_portfolio_drawdown_from_crypto / denominador if denominador > 0 else 0.0
        ),
        "hard_cap": r.max_crypto_weight,
    }
    if vol_annual is not None and vol_annual > 0:
        candidatos["vol_target"] = r.crypto_vol_target / vol_annual

    restriccion = min(candidatos, key=lambda k: candidatos[k])
    mult = min(max(multiplicador, 0.0), 1.0)  # nunca amplifica; ver risk.py
    peso = min(candidatos.values()) * mult
    if mult < 1.0:
        restriccion = f"multiplicador({mult:.2f})"
    if peso < r.min_crypto_weight:
        peso, restriccion = 0.0, "below_floor"

    investable = max(
        policy.portfolio.total_capital_mxn - policy.portfolio.liquidity_reserve_mxn, 0.0
    )
    return peso, investable * peso, restriccion


def escenarios_banxico(
    hurdle_actual: float,
    cetes_curve: dict[int, float],
    policy: Policy,
    inflacion: float,
    vol_annual: float | None = None,
    multiplicador: float = 1.0,
    movimientos: tuple[tuple[int, str], ...] = MOVIMIENTOS_BANXICO,
) -> list[EscenarioBanxico]:
    """
    Tabla pre-computada: para cada resultado posible de la decisión, el hurdle
    resultante y el sleeve objetivo en MXN.

    `hurdle_actual` es el hurdle ANUALIZADO vigente (el de decide.py). Se usa
    sólo como referencia de los deltas y como verificación cruzada: si el
    escenario "sin cambio" no reproduce ese número, algo no cuadra —
    típicamente que llegó el hurdle DEL PERIODO en vez del anualizado, que es
    el error más caro que tuvo este motor. Truena en vez de publicar una tabla
    con la escala equivocada.

    `cetes_curve` en decimal (0.0701), igual que `banxico.cetes_curve`.
    """
    if not cetes_curve:
        raise ValueError("Curva CETES vacía: no hay nada que desplazar.")

    horizonte = policy.portfolio.horizon_days
    tenor, _ = pick_hurdle_tenor(cetes_curve, horizonte)

    out: list[EscenarioBanxico] = []
    base_hurdle: float | None = None
    base_sleeve: float | None = None

    for bp, etiqueta in movimientos:
        # Desplazamiento PARALELO. Es el supuesto, y va escrito en la salida.
        curva = {t: v + bp / 10_000.0 for t, v in cetes_curve.items()}
        nominal = curva[tenor]
        hurdle_anual, ny = hurdle_rate(nominal, inflacion, policy.tax, policy.required_risk_premium)
        peso, sleeve, restriccion = _sleeve_objetivo(
            policy, ny.net_nominal_rate, vol_annual, multiplicador
        )
        if bp == 0:
            base_hurdle, base_sleeve = hurdle_anual, sleeve
            if abs(hurdle_anual - hurdle_actual) > 0.0025:
                raise ValueError(
                    f"El escenario 'sin cambio' da hurdle {hurdle_anual:.4%} pero se recibió"
                    f" hurdle_actual={hurdle_actual:.4%}. ¿Se pasó el hurdle DEL PERIODO en"
                    " vez del anualizado, u otra inflación? No se publica la tabla."
                )
        out.append(
            EscenarioBanxico(
                movimiento_bp=bp,
                etiqueta=etiqueta,
                tenor_days=tenor,
                cetes_nominal=nominal,
                cetes_neto_nominal=ny.net_nominal_rate,
                hurdle_anualizado=hurdle_anual,
                hurdle_periodo=annualized_to_period(hurdle_anual, horizonte),
                delta_hurdle_bp=0.0,
                peso_objetivo=peso,
                sleeve_objetivo_mxn=sleeve,
                delta_sleeve_mxn=0.0,
                restriccion=restriccion,
                supuestos=SUPUESTOS_ESCENARIOS,
            )
        )

    if base_hurdle is None or base_sleeve is None:
        raise ValueError(
            "El set de movimientos debe incluir 'sin cambio' (0 pb): sin él no hay"
            " referencia contra la cual medir los deltas."
        )

    # Los deltas se llenan al final: el escenario base no tiene por qué ser el
    # primero de la lista, así que no se puede restar sobre la marcha.
    return [
        replace(
            e,
            delta_hurdle_bp=(e.hurdle_anualizado - base_hurdle) * 10_000.0,
            delta_sleeve_mxn=e.sleeve_objetivo_mxn - base_sleeve,
        )
        for e in out
    ]
