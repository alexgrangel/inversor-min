"""
El combinador. Convierte indicadores de estrés y noticias en UN multiplicador.

LA INVARIANTE QUE GOBIERNA TODO ESTE ARCHIVO:

    Las noticias y el estrés SÓLO pueden reducir tamaño o levantar un bloqueo.
    NUNCA pueden aumentar tamaño y NUNCA pueden originar una compra.

No es una preferencia de diseño, es el diseño. Una cuenta chica se destruye por
sobre-operar reaccionando a titulares, y el presupuesto de comisiones de este
repo alcanza para ~1.7 round-trips AL AÑO (ver costs.py). Un sistema que puede
decir "compra porque el índice de miedo está en 12" gasta ese presupuesto en
tres semanas. Este no puede decirlo: el rango del multiplicador es [0.0, 1.0]
y se impone en `__post_init__`, no por convención ni por revisión de código.
Cualquier `SignalState`, construido como sea, sale con el multiplicador dentro
de rango o no sale.

Consecuencias que se siguen de la invariante y que están codificadas abajo:

  - Greed extremo en el Fear & Greed contribuye 1.0. No 1.2. Miedo extremo sí
    recorta. La asimetría es el punto entero.
  - Una fuente caída RECORTA. Un feed de estrés que no responde no es evidencia
    de calma; es incertidumbre sobre el estado del mundo, y la incertidumbre se
    paga con menos posición.
  - Los recortes se combinan con MÍNIMO, no con producto. F&G, DVOL y VIX leen
    el mismo estado del mundo por tres ventanas distintas; multiplicarlos
    cuenta el mismo estrés tres veces y manda el sleeve a cero por aritmética,
    no por riesgo. Es el mismo criterio de `regime.blended_multiplier` y de
    `risk.size_crypto_sleeve`: manda la restricción que más aprieta.

Nada de aquí pronostica. "Miedo extremo" no significa que el precio vaya a
bajar; significa que estamos en el régimen donde una cuenta chica menos se
puede permitir estar grande.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .sources.market_stress import MAX_STALE_DIAS, StressReading
from .sources.news import RupturaEstructural, VolumenAnomalo

# Umbrales y recortes. Son JUICIOS, no datos: por eso viven nombrados y juntos
# en vez de dispersos como números mágicos, igual que en regime.py. Cambiar
# cualquiera exige justificarlo, y "en el backtest daba mejor" no es
# justificación (CLAUDE.md regla 1).
#
# Ningún valor de esta tabla puede ser > 1.0. Si alguien pone 1.2 aquí, el
# clamp de `_recorte` lo devuelve a 1.0 y el test de propiedad lo demuestra.
FG_MIEDO_EXTREMO = 25.0        # el índice va de 0 (pánico) a 100 (euforia)
FG_MIEDO = 40.0
MULT_FG_MIEDO_EXTREMO = 0.50
MULT_FG_MIEDO = 0.75

DVOL_ELEVADO = 65.0            # puntos de vol implícita anualizada
DVOL_EXTREMO = 90.0
MULT_DVOL_ELEVADO = 0.70
MULT_DVOL_EXTREMO = 0.40

VIX_ELEVADO = 25.0
VIX_EXTREMO = 35.0
MULT_VIX_ELEVADO = 0.70
MULT_VIX_EXTREMO = 0.40

MULT_VOLUMEN_ANOMALO = 0.70

# Dos o más fuentes caídas dejan de ser mala suerte y pasan a ser ceguera sobre
# el estado del mercado. Una sola caída no recorta: los otros indicadores
# todavía cubren el mismo régimen.
FUENTES_CAIDAS_QUE_RECORTAN = 2
MULT_FUENTES_CAIDAS = 0.60

# Techo absoluto. Existe como constante para que sea imposible escribir una
# regla que devuelva más de esto sin que se note en el diff.
MULT_MAXIMO = 1.0

# Un día de holgura para antigüedades negativas. Los fetchers fechan en UTC y
# `date.today()` es la fecha LOCAL: corriendo desde México a las 19:00 la barra
# de hoy ya está estampada mañana en UTC y saldría con −1 día. Más allá de un
# día no es huso horario: es reloj descompuesto o payload manipulado.
TOLERANCIA_FUTURO_DIAS = 1


def _clamp(x: Any) -> float:
    """
    Todo lo que quiera ser un multiplicador pasa por aquí.

    NaN, None, strings y objetos raros colapsan a 0.0, no a 1.0. En un sistema
    cuya salida más valiosa es "no operes", el valor por defecto de lo
    desconocido es la posición más chica, no la más grande. 0.0 no borra tu
    posición actual: `decide.py` sólo opera si además libra la banda de
    no-operación y el presupuesto de comisiones.
    """
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        # OverflowError es el caso de un int gigante (10**400): float() truena.
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(MULT_MAXIMO, v))


@dataclass(frozen=True)
class SignalState:
    """
    Resultado del combinador.

    `multiplicador` está garantizado en [0.0, 1.0] por construcción: el
    `__post_init__` lo pasa por `_clamp` incluso si alguien construye el
    dataclass a mano con 7.0. Es lo más cerca del sistema de tipos que llega
    Python sin un tipo refinado.
    """
    multiplicador: float
    blockers: list[str] = field(default_factory=list)
    razones: list[str] = field(default_factory=list)
    fuentes_no_disponibles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # frozen=True bloquea la asignación normal; object.__setattr__ es la
        # vía documentada para normalizar en el constructor.
        object.__setattr__(self, "multiplicador", _clamp(self.multiplicador))

    def aplicar(self, multiplicador_base: float) -> float:
        """
        Compone con el multiplicador de régimen tomando el MÍNIMO, no el
        producto. El régimen (SMA/percentil de vol) y las señales (F&G, DVOL,
        VIX) leen el MISMO estado de estrés por ventanas distintas:
        multiplicarlos cuenta el mismo estrés dos veces — 0.30 de régimen por
        0.60 de señales daría 0.18, un doble castigo por un solo hecho. Manda
        el que más aprieta. Por construcción el resultado es
        <= multiplicador_base: las señales aprietan, nunca aflojan.
        """
        base = _clamp(multiplicador_base)
        return min(base, self.multiplicador)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "multiplicador": self.multiplicador,
            "blockers": list(self.blockers),
            "razones": list(self.razones),
            "fuentes_no_disponibles": list(self.fuentes_no_disponibles),
        }


def _recorte(valor: float) -> float:
    """Un recorte nunca puede ser una amplificación. Ver MULT_MAXIMO."""
    return _clamp(valor)


def _lectura(obj: Any, hoy: date, max_dias: int | None, etiqueta: str) -> tuple[float | None, str]:
    """
    Extrae el valor numérico usable de un StressReading, o explica por qué no.

    Se lee con getattr y no con acceso directo a propósito: un bug en un fetcher
    (o un fixture adversarial de los tests) no puede tirar el motor entero. La
    firma pide StressReading porque es lo que debe llegar; el cuerpo no lo
    asume porque el costo de equivocarse es un crash en el cron diario.
    """
    if obj is None:
        return None, f"{etiqueta}: sin dato."
    valor = getattr(obj, "value", None)
    try:
        v = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None, f"{etiqueta}: valor no numérico ({valor!r})."
    if v != v:
        return None, f"{etiqueta}: valor NaN."

    stale_days = getattr(obj, "stale_days", None)
    limite = max_dias if max_dias is not None else MAX_STALE_DIAS.get(etiqueta, 5)
    try:
        d = int(stale_days)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None, f"{etiqueta}: antigüedad desconocida; no se usa (regla 4)."
    if d > limite:
        return None, f"{etiqueta}: {d} días de antigüedad (límite {limite}); rancio."
    if d < -TOLERANCIA_FUTURO_DIAS:
        return None, f"{etiqueta}: fecha en el futuro ({d} días); dato inconsistente."
    return v, ""


def combinar(
    fear_greed: StressReading | None = None,
    dvol: StressReading | None = None,
    vix: StressReading | None = None,
    volumen: VolumenAnomalo | None = None,
    ruptura: RupturaEstructural | None = None,
    fuentes_no_disponibles: Any = (),
    apagadas: Any = (),
    hoy: date | None = None,
    max_staleness_days: int | None = None,
) -> SignalState:
    """
    Combina todo en un SignalState. NUNCA devuelve un multiplicador > 1.0.

    Todos los parámetros son opcionales: llamar sin nada devuelve el estado
    "no sé nada", que recorta por ceguera y no por estrés. Cualquier entrada
    inutilizable (None, NaN, rancia, con forma equivocada) se contabiliza como
    fuente no disponible, no como fuente en calma.

    `apagadas` distingue "no se consultó por decisión de política" de "se
    consultó y no respondió". Una fuente APAGADA por bandera (hoy: GDELT y
    DOF hasta el Prompt 6) no entra al conteo de ceguera — sin este estado,
    apagar dos fuentes activaba el recorte de 0.60x permanentemente y el
    recorte dejaba de ser información. Sólo aplica a volumen_noticias y
    ruptura_estructural: los indicadores de estrés no tienen bandera a
    propósito, su fallo SÍ es ceguera. Una fuente apagada jamás se lee como
    calma: simplemente no opina.
    """
    hoy = hoy or date.today()
    razones: list[str] = []
    blockers: list[str] = []
    caidas: list[str] = [str(x) for x in _como_lista(fuentes_no_disponibles)]
    apagadas_set = {str(x).strip().casefold() for x in _como_lista(apagadas)}
    recortes: list[float] = [MULT_MAXIMO]

    # ---------- Fear & Greed ----------
    # El motivo ya viene etiquetado por _lectura; re-prefijarlo producía
    # renglones tipo "fear_greed: fear_greed: sin dato." en el snapshot.
    v, motivo = _lectura(fear_greed, hoy, max_staleness_days, "fear_greed")
    if v is None:
        caidas.append(motivo)
    elif v <= FG_MIEDO_EXTREMO:
        recortes.append(_recorte(MULT_FG_MIEDO_EXTREMO))
        razones.append(
            f"Fear & Greed en {v:.0f} (miedo extremo, ≤ {FG_MIEDO_EXTREMO:.0f}):"
            f" tamaño x{MULT_FG_MIEDO_EXTREMO:.2f}. NO es un pronóstico de rebote ni de"
            " caída; es el régimen donde una cuenta chica menos aguanta estar grande."
        )
    elif v <= FG_MIEDO:
        recortes.append(_recorte(MULT_FG_MIEDO))
        razones.append(
            f"Fear & Greed en {v:.0f} (miedo, ≤ {FG_MIEDO:.0f}): tamaño x{MULT_FG_MIEDO:.2f}."
        )
    else:
        razones.append(
            f"Fear & Greed en {v:.0f}: sin recorte (x1.00). La codicia NO aumenta tamaño;"
            " el multiplicador está acotado en 1.00 por construcción."
        )

    # ---------- DVOL ----------
    v, motivo = _lectura(dvol, hoy, max_staleness_days, "dvol_btc")
    if v is None:
        caidas.append(motivo)
    elif v >= DVOL_EXTREMO:
        recortes.append(_recorte(MULT_DVOL_EXTREMO))
        razones.append(
            f"DVOL en {v:.1f} (≥ {DVOL_EXTREMO:.0f}, vol implícita extrema):"
            f" tamaño x{MULT_DVOL_EXTREMO:.2f}."
        )
    elif v >= DVOL_ELEVADO:
        recortes.append(_recorte(MULT_DVOL_ELEVADO))
        razones.append(
            f"DVOL en {v:.1f} (≥ {DVOL_ELEVADO:.0f}): tamaño x{MULT_DVOL_ELEVADO:.2f}."
        )
    else:
        razones.append(f"DVOL en {v:.1f}: por debajo de {DVOL_ELEVADO:.0f}, sin recorte.")

    # ---------- VIX ----------
    v, motivo = _lectura(vix, hoy, max_staleness_days, "vix")
    if v is None:
        caidas.append(motivo)
    elif v >= VIX_EXTREMO:
        recortes.append(_recorte(MULT_VIX_EXTREMO))
        razones.append(
            f"VIX en {v:.1f} (≥ {VIX_EXTREMO:.0f}): tamaño x{MULT_VIX_EXTREMO:.2f}."
        )
    elif v >= VIX_ELEVADO:
        recortes.append(_recorte(MULT_VIX_ELEVADO))
        razones.append(f"VIX en {v:.1f} (≥ {VIX_ELEVADO:.0f}): tamaño x{MULT_VIX_ELEVADO:.2f}.")
    else:
        razones.append(f"VIX en {v:.1f}: por debajo de {VIX_ELEVADO:.0f}, sin recorte.")

    # ---------- Volumen de noticias ----------
    if volumen is None and "volumen_noticias" in apagadas_set:
        razones.append(
            "Volumen de noticias: fuente apagada por bandera (GDELT pendiente de"
            " estabilizarse). No cuenta como ceguera ni como calma: no opina."
        )
    elif volumen is None or not getattr(volumen, "disponible", False):
        nota = getattr(volumen, "nota", "sin dato") if volumen is not None else "sin dato"
        caidas.append(f"volumen_noticias: {nota}")
    elif getattr(volumen, "anomalo", False):
        z = getattr(volumen, "z", None)
        recortes.append(_recorte(MULT_VOLUMEN_ANOMALO))
        razones.append(
            f"Volumen de noticias anómalo (z = {_fmt(z)}): tamaño x{MULT_VOLUMEN_ANOMALO:.2f}."
            " Corrobora estrés ya visible en precio; por sí solo no origina nada."
        )
    else:
        razones.append(
            f"Volumen de noticias dentro de su línea base"
            f" (z = {_fmt(getattr(volumen, 'z', None))})."
        )

    # ---------- Ruptura estructural ----------
    if ruptura is None and "ruptura_estructural" in apagadas_set:
        razones.append(
            "Ruptura estructural: fuente apagada por bandera. No cuenta como"
            " ceguera ni como calma: no opina."
        )
    elif ruptura is None or not getattr(ruptura, "disponible", False):
        nota = getattr(ruptura, "nota", "sin dato") if ruptura is not None else "sin dato"
        caidas.append(f"ruptura_estructural: {nota}")
    elif getattr(ruptura, "detectada", False):
        for c in _como_lista(getattr(ruptura, "coincidencias", ())):
            blockers.append(
                f"RUPTURA ESTRUCTURAL — {getattr(c, 'etiqueta', 'sin etiqueta')}:"
                f" \"{getattr(c, 'titulo', '')}\" ({getattr(c, 'fuente', '?')})."
                " Requiere revisión humana antes de operar."
            )
        if not blockers:
            blockers.append(
                "RUPTURA ESTRUCTURAL detectada sin detalle de coincidencias."
                " Requiere revisión humana antes de operar."
            )
        razones.append(
            f"{len(blockers)} coincidencia(s) con la lista curada de rupturas regulatorias."
            " Un bloqueo no se resuelve con un multiplicador: se resuelve leyendo."
        )
    else:
        razones.append(
            f"Sin rupturas regulatorias en {getattr(ruptura, 'notas_revisadas', 0)} notas"
            " revisadas."
        )

    # ---------- Ceguera ----------
    caidas = [c for c in caidas if c and str(c).strip()]
    # El umbral cuenta FUENTES únicas, no renglones: una misma fuente caída
    # puede llegar dos veces (el renglón del recolector aguas arriba Y el del
    # slot en None), y contar renglones disparaba el recorte por ceguera con
    # una sola fuente real caída.
    fuentes_ciegas = {_fuente_de_caida(c) for c in caidas}
    if len(fuentes_ciegas) >= FUENTES_CAIDAS_QUE_RECORTAN:
        recortes.append(_recorte(MULT_FUENTES_CAIDAS))
        razones.append(
            f"{len(fuentes_ciegas)} fuentes no disponibles"
            f" (≥ {FUENTES_CAIDAS_QUE_RECORTAN}):"
            f" tamaño x{MULT_FUENTES_CAIDAS:.2f}. No saber en qué estado está el mercado"
            " es en sí mismo una razón para tener menos, nunca para tener lo mismo."
        )
    elif caidas:
        razones.append(
            f"1 fuente no disponible ({caidas[0][:80]}): sin recorte todavía, los demás"
            " indicadores cubren el mismo régimen."
        )

    # Mínimo, no producto: los indicadores están correlacionados y multiplicarlos
    # cuenta el mismo estrés varias veces. Manda el que más aprieta.
    mult = _clamp(min(recortes))
    razones.append(
        f"Multiplicador de señales: {mult:.2f} (mínimo de {len(recortes)} recortes;"
        " acotado a [0.00, 1.00] por construcción, nunca amplifica)."
    )
    return SignalState(
        multiplicador=mult,
        blockers=blockers,
        razones=razones,
        fuentes_no_disponibles=caidas,
    )


def _fuente_de_caida(renglon: str) -> str:
    """
    La fuente de un renglón de caída: el texto antes del primer ':'. dvol_btc
    y dvol_eth colapsan a 'dvol' porque alimentan el mismo slot del combinador
    (el recolector etiqueta 'dvol_btc: ...' y el slot en None 'dvol...').
    """
    etiqueta = str(renglon).split(":", 1)[0].strip().casefold()
    return "dvol" if etiqueta.startswith("dvol") else etiqueta


def _como_lista(x: Any) -> list[Any]:
    """Normaliza cualquier cosa iterable-o-no a una lista, sin tronar."""
    if x is None:
        return []
    if isinstance(x, (str, bytes)):
        return [x]
    try:
        return list(x)
    except TypeError:
        return [x]


def _fmt(z: Any) -> str:
    try:
        v = float(z)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return "n/d"
    return "n/d" if v != v else f"{v:+.2f}"
