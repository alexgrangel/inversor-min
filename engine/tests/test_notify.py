"""
Tests del motor de notificaciones. Cero red.

La tesis del módulo es una sola frase: **no se te puede pedir actuar más veces
de las que puedes pagar actuar**. El presupuesto de comisiones autoriza ~1.7
round-trips AL AÑO (costs.py), así que un sistema de avisos que habla seguido
no es una funcionalidad, es el modo de falla: así se destruye una cuenta chica.

Por eso aquí no se prueba "el código corre". Se prueba, con entrada adversaria,
que la maquinaria anti-spam aguanta:

  - El silencio es el default. Estado idéntico ⇒ cero avisos.
  - Cada trigger respeta su cooldown, uno por uno.
  - Los triggers numéricos no oscilan (histéresis con banda de re-arme).
  - En un año simulado de entrada adversaria, los avisos que pueden costar
    comisiones no superan lo que el presupuesto de comisiones paga.
  - HIGH no puede usarse como bypass permanente del tope global.
  - Ningún aviso publica un número que no tiene.

Las Decisions se construyen a partir de una corrida REAL del engine (`decide`
sobre observaciones sintéticas), no de literales escritos a mano: regla 5 del
repo, ningún número inventado en los fixtures.
"""
from __future__ import annotations

import copy
import inspect
import json
import math
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from inversor import notify as notify_mod
from inversor import notify_sinks as sinks_mod
from inversor.config import Policy
from inversor.decide import Decision, decide
from inversor.notify import (
    KIND_ESTADO,
    KIND_NOTIFICACION,
    KIND_SUPRESION,
    MAX_TITULO,
    PRIORIDAD_POR_TRIGGER,
    TRIGGERS,
    Notification,
    NotifyPolicy,
    evaluate,
    evaluate_with_audit,
)
from inversor.notify_sinks import render_markdown, render_ntfy
from inversor.sources.banxico import Observation

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ fixtures


def _synth(n=500, start=100.0, drift=0.0004, vol=0.03, seed=7):
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= math.exp(drift + rng.gauss(0, vol))
        out.append(p)
    return out


def _obs(**over):
    base = {
        "fix_usdmxn": 17.1387,
        "cetes_28": 6.17,
        "cetes_91": 6.40,
        "cetes_182": 6.75,
        "cetes_364": 7.01,
        "tasa_objetivo": 6.50,
        "inpc_anual": 3.12,
    }
    base.update(over)
    d = date(2026, 8, 10)
    return {k: Observation(k, "TEST", v, d, 1) for k, v in base.items()}


# Una corrida real del engine. Todo número que aparezca en los fixtures sale de
# aquí, no de un literal: si el engine cambia, los tests cambian con él.
_BASE: Decision = decide(
    Policy(),
    _obs(),
    {"BTC": _synth(seed=3, vol=0.03), "ETH": _synth(seed=4, vol=0.04)},
)

# El presupuesto de comisiones que consume el notificador. Es el dict serializado
# que el CLI le pasa (`d.costs`), idéntico al de snapshots/latest.json.
COSTOS: dict[str, Any] = copy.deepcopy(_BASE.costs)
MAX_ROUND_TRIPS: float = float(COSTOS["max_round_trips_per_year"])

OPERABLES = ("STAY_IN_CETES", "ALLOCATE_TO_CRYPTO", "REDUCE_CRYPTO", "HOLD_NO_ACTION")

# Frases que el módulo emite SÓLO cuando te está diciendo que muevas dinero
# (`_plan_operativo` / plan de materialidad). Son las que cuestan comisiones.
_ORDEN_EJECUTABLE = re.compile(
    r"(?:^|\s)(?:Mover \d|Vender hasta dejar|Considera cerrar el sleeve)"
)

# Su contraparte: la frase que cierra la pregunta "¿muevo dinero hoy?" con un no.
_NO_OPERAR = re.compile(
    r"No operes|No abras|No ejecutes por este aviso|Cero órdenes|nada que ejecutar"
    r"|No hay operación que ejecutar|NO es razón para aumentarlo|No aumentes posición"
)

# Basura que nunca debe llegar al teléfono: repr de objeto, hueco sin formato,
# float crudo con más de 6 decimales.
_BASURA = re.compile(r"\bNone\b|\bnan\b|\binf\b|<[\w.]+ object at 0x[0-9a-f]+>|\d\.\d{7,}")


def dec(
    dia: float = 0.0,
    *,
    action: str | None = None,
    blockers: list[str] | None = None,
    hurdle: float | None = None,
    round_trips: float | None = None,
    materialidad: str | None = None,
    regimenes: list[str] | None = None,
    sleeve: float | None = None,
    headline: str | None = None,
    schema_version: str | None = None,
    degradada: bool = False,
) -> Decision:
    """
    Decision del día `dia` (offset en días desde T0), con overrides.

    `degradada=True` reproduce la salida real de decide.py cuando los datos están
    rancios: hurdle, sizing, costs, required_returns y allocation VACÍOS.
    """
    d = copy.deepcopy(_BASE)
    d.generated_at = (T0 + timedelta(days=dia)).isoformat()
    if action is not None:
        d.action = action
    if blockers is not None:
        d.blockers = list(blockers)
    if headline is not None:
        d.headline = headline
    if schema_version is not None:
        d.schema_version = schema_version
    if hurdle is not None:
        d.hurdle["hurdle_total_anualizado"] = hurdle
    if round_trips is not None:
        d.costs["round_trips_remaining"] = round_trips
    if materialidad is not None:
        d.sizing["materiality"]["veredicto"] = materialidad
    if regimenes is not None:
        for i, label in enumerate(regimenes):
            d.sizing["regimes"][i]["label"] = label
    if sleeve is not None:
        d.sizing["weight_mxn"] = sleeve
    if degradada:
        d.action = "BLOCKED_STALE_DATA"
        d.headline = "Datos rancios. No se emite recomendación ni se calcula nada más."
        d.hurdle = {}
        d.sizing = {}
        d.costs = {}
        d.required_returns = {}
        d.allocation_mxn = {}
        d.market = {}
        d.fx = {}
    return d


class Cron:
    """
    Reproduce el bucle real del CLI (`__main__.cmd_notify_step`).

    El historial append-only es la ÚNICA memoria entre corridas: sin threading de
    los registros de auditoría (`estado`), la histéresis no existe. Un test que
    llame a `evaluate` con historial vacío cada día está probando otro programa.
    """

    def __init__(
        self,
        policy: NotifyPolicy | None = None,
        cost_budget: Any = None,
    ) -> None:
        self.policy = policy or NotifyPolicy()
        self.cost_budget = COSTOS if cost_budget is None else cost_budget
        self.history: list[dict[str, Any]] = []
        self.previous: Decision | None = None
        self.emitidas: list[tuple[float, Notification]] = []
        self.suprimidas: list[dict[str, Any]] = []

    def dia(self, d: Decision) -> list[Notification]:
        ns, auditoria = evaluate_with_audit(
            d, self.previous, self.history, self.policy, self.cost_budget
        )
        cuando = notify_mod._parse_iso(d.generated_at)
        offset = (cuando - T0).total_seconds() / 86_400.0
        self.emitidas += [(offset, n) for n in ns]
        self.suprimidas += [r for r in auditoria if r.get("kind") == KIND_SUPRESION]
        self.history.extend([n.to_record() for n in ns])
        self.history.extend(auditoria)
        self.previous = d
        return ns

    def cuenta(self, trigger: str) -> int:
        return sum(1 for _, n in self.emitidas if n.trigger == trigger)

    def total(self) -> int:
        return len(self.emitidas)

    def peor_ventana(self, dias: int) -> int:
        """Máximo de avisos entregados dentro de cualquier ventana de `dias`."""
        peor = 0
        for inicio, _ in self.emitidas:
            n = sum(1 for o, _ in self.emitidas if inicio - dias <= o <= inicio)
            peor = max(peor, n)
        return peor

    def ordenes_ejecutables(self) -> list[Notification]:
        """Avisos cuyo texto contiene una instrucción de mover dinero."""
        return [
            n
            for _, n in self.emitidas
            if any(_ORDEN_EJECUTABLE.search(t) for t in n.estrategia)
        ]


def texto(n: Notification) -> str:
    """Todo lo que el usuario llega a leer en el teléfono."""
    return " \n".join([n.title, n.body, *n.razonamiento, *n.estrategia])


# ============================================================================
# 1. EL SILENCIO ES EL DEFAULT
# ============================================================================


def test_estado_identico_no_produce_ninguna_notificacion():
    """La invariante 1 del módulo. Si esto falla, todo lo demás da igual."""
    ayer, hoy = dec(0), dec(1)
    assert evaluate(hoy, ayer, [], NotifyPolicy(), COSTOS) == []


def test_treinta_dias_identicos_producen_silencio_total():
    """Un nivel que no cambia no es noticia, ni el día 1 ni el día 30."""
    cron = Cron()
    for d in range(31):
        cron.dia(dec(d))
    assert cron.total() == 0
    assert cron.suprimidas == []


def test_primera_corrida_sin_previo_no_avisa_nada():
    """previous=None ⇒ no hay transición que reportar. Ni siquiera informativa."""
    ns, auditoria = evaluate_with_audit(dec(0), None, [], NotifyPolicy(), COSTOS)
    assert ns == []
    assert auditoria == []


def test_primera_corrida_nunca_emite_un_aviso_de_accion():
    """
    Aunque el snapshot del primer día traiga bloqueos, presupuesto agotado y un
    hurdle disparatado: sin `previous` no se puede gastar el presupuesto anual de
    avisos operables sólo por arrancar el sistema.
    """
    d = dec(
        0,
        action="ALLOCATE_TO_CRYPTO",
        blockers=["algo: 40 días de antigüedad (límite 5)."],
        hurdle=0.35,
        round_trips=0.1,
        materialidad="MATERIAL",
    )
    ns = evaluate(d, None, [], NotifyPolicy(), COSTOS)
    assert ns == []


def test_el_historial_previo_no_resucita_avisos_en_la_primera_corrida():
    """Historial viejo + previous=None sigue siendo silencio."""
    historial = [
        {
            "kind": KIND_NOTIFICACION,
            "trigger": "ACTION_CHANGED",
            "priority": "HIGH",
            "fired_at": (T0 - timedelta(days=2)).isoformat(),
            "dedup_key": "ACTION_CHANGED:X->Y",
        }
    ]
    assert evaluate(dec(0), None, historial, NotifyPolicy(), COSTOS) == []


# ============================================================================
# 2. EL COOLDOWN AGUANTA — UNO POR TRIGGER
# ============================================================================


def _ciclo(
    escenario,
    trigger: str,
    *,
    dentro: float,
    fuera: float,
    policy: NotifyPolicy | None = None,
) -> None:
    """
    Dispara `trigger`, lo vuelve a provocar DENTRO de su cooldown (debe callarse
    con motivo `cooldown`) y después de él (debe volver a hablar).

    `escenario(dia)` devuelve (previous, current) para ese día.
    """
    policy = policy or NotifyPolicy()
    cd = policy.cooldown_for(trigger)
    assert cd > 0, f"{trigger} sin cooldown declarado"

    cron = Cron(policy)
    prev, cur = escenario(0.0)
    cron.previous = prev
    ns = cron.dia(cur)
    assert trigger in [n.trigger for n in ns], f"{trigger} no disparó en el día 0: {ns}"

    prev, cur = escenario(dentro)
    cron.previous = prev
    ns = cron.dia(cur)
    assert trigger not in [n.trigger for n in ns], (
        f"{trigger} volvió a disparar a los {dentro} días con cooldown de {cd}"
    )
    motivos = [r["motivo"] for r in cron.suprimidas if r["trigger"] == trigger]
    assert motivos, f"{trigger} se calló sin dejar registro de supresión"
    assert motivos[-1] in ("cooldown", "dedup"), motivos

    prev, cur = escenario(fuera)
    cron.previous = prev
    ns = cron.dia(cur)
    assert trigger in [n.trigger for n in ns], (
        f"{trigger} siguió mudo a los {fuera} días con cooldown de {cd}"
    )


def test_cooldown_action_changed():
    def esc(dia):
        par = ("STAY_IN_CETES", "ALLOCATE_TO_CRYPTO")
        return dec(dia, action=par[0]), dec(dia, action=par[1])

    # El presupuesto anual (1 aviso) se relaja a propósito: aquí se aísla el
    # cooldown. Que el presupuesto mande sobre él se prueba aparte.
    _ciclo(
        esc,
        "ACTION_CHANGED",
        dentro=2.0,
        fuera=3.0,
        policy=NotifyPolicy(max_action_changes_per_year=99),
    )


def test_el_presupuesto_anual_manda_sobre_el_cooldown_de_action_changed():
    """Pasado el cooldown de 3 días el trigger vuelve a ser candidato, pero el
    presupuesto de comisiones lo tumba igual y en su lugar sale la meta-alerta."""
    cron = Cron()
    cron.previous = dec(0, action="STAY_IN_CETES")
    assert [n.trigger for n in cron.dia(dec(0, action="ALLOCATE_TO_CRYPTO"))] == ["ACTION_CHANGED"]
    cron.previous = dec(3, action="STAY_IN_CETES")
    ns = cron.dia(dec(3, action="ALLOCATE_TO_CRYPTO"))
    assert "ACTION_CHANGED" not in [n.trigger for n in ns]
    assert any(
        r["motivo"] == "presupuesto_anual_de_acciones" for r in cron.suprimidas
    ), cron.suprimidas


def test_cooldown_blocker_raised():
    def esc(dia):
        return (
            dec(dia, blockers=[]),
            dec(dia, blockers=[f"serie_{int(dia * 24)}: 9 días de antigüedad (límite 5)."]),
        )

    # 3 días, no 1: con cadencia diaria del cron un cooldown de 1 día no silencia
    # nada, porque dos corridas consecutivas están a exactamente 1.0 días y la
    # comparación es estricta.
    _ciclo(esc, "BLOCKER_RAISED", dentro=2.0, fuera=3.0)


def test_cooldown_blocker_cleared():
    def esc(dia):
        b = f"serie_{int(dia * 24)}: 9 días de antigüedad (límite 5)."
        return dec(dia, blockers=[b]), dec(dia, blockers=[])

    _ciclo(esc, "BLOCKER_CLEARED", dentro=2.0, fuera=3.0)


def test_cooldown_fee_budget_low():
    def esc(dia):
        return dec(dia, round_trips=1.4), dec(dia, round_trips=0.4)

    _ciclo(esc, "FEE_BUDGET_LOW", dentro=89.0, fuera=90.0)


def test_cooldown_regime_flipped():
    def esc(dia):
        # Alterna el par de etiquetas para que el dedup_key cambie y el que mande
        # sea el cooldown del trigger.
        a, b = (["NEUTRAL", "NEUTRAL"], ["RISK_OFF", "NEUTRAL"])
        return dec(dia, regimenes=a), dec(dia, regimenes=b)

    _ciclo(esc, "REGIME_FLIPPED", dentro=13.0, fuera=14.0)


def test_cooldown_hurdle_moved():
    """
    La referencia de este trigger se mueve al avisar, así que el ciclo genérico
    no aplica: hay que re-armar la histéresis antes de volver a provocarlo.
    """
    policy = NotifyPolicy()
    cd = policy.cooldown_for("HURDLE_MOVED")
    base = 0.10843
    cron = Cron(policy)

    cron.dia(dec(0, hurdle=base))
    ns = cron.dia(dec(1, hurdle=base + 0.0060))
    assert [n.trigger for n in ns] == ["HURDLE_MOVED"]

    # Vuelve a la referencia: re-arma sin avisar (no hay movimiento que reportar).
    assert cron.dia(dec(cd - 2, hurdle=base + 0.0060)) == []

    # Se mueve otros 60 pb hacia un nivel NUEVO, dentro del cooldown: se calla y
    # lo registra. Tiene que ser un nivel nuevo: volver a uno ya avisado no es
    # noticia y ni siquiera llega a ser candidato.
    ns = cron.dia(dec(cd - 1, hurdle=base + 0.0120))
    assert "HURDLE_MOVED" not in [n.trigger for n in ns]
    assert any(
        r["trigger"] == "HURDLE_MOVED" and r["motivo"] == "cooldown" for r in cron.suprimidas
    ), cron.suprimidas

    # Fuera del cooldown vuelve a hablar.
    ns = cron.dia(dec(cd + 1, hurdle=base + 0.0120))
    assert "HURDLE_MOVED" in [n.trigger for n in ns]


def test_cooldown_materiality_flipped():
    def esc(dia):
        return dec(dia, materialidad="MATERIAL"), dec(dia, materialidad="INMATERIAL")

    # "Considera cerrar el sleeve" es una orden ejecutable y por lo tanto se cobra
    # contra el presupuesto anual; aquí se relaja para aislar el cooldown.
    _ciclo(
        esc,
        "MATERIALITY_FLIPPED",
        dentro=29.0,
        fuera=30.0,
        policy=NotifyPolicy(max_action_changes_per_year=99),
    )


def test_cooldown_overtrading_detected():
    """
    La meta-notificación también respeta cooldown: si no, el propio aviso de
    "estás generando demasiada señal" se vuelve la señal más ruidosa del sistema.
    """
    policy = NotifyPolicy()
    cd = policy.cooldown_for("OVERTRADING_DETECTED")
    cron = Cron(policy)

    # Gasta el presupuesto anual de acciones (permitidos = floor(1.67) = 1).
    cron.previous = dec(0, action="STAY_IN_CETES")
    ns = cron.dia(dec(0, action="ALLOCATE_TO_CRYPTO"))
    assert [n.trigger for n in ns] == ["ACTION_CHANGED"]

    def cambia(dia):
        par = ("STAY_IN_CETES", "ALLOCATE_TO_CRYPTO")
        cron.previous = dec(dia, action=par[0])
        return [n.trigger for n in cron.dia(dec(dia, action=par[1]))]

    assert "OVERTRADING_DETECTED" in cambia(10.0)
    assert "OVERTRADING_DETECTED" not in cambia(10.0 + cd - 1)
    assert "OVERTRADING_DETECTED" in cambia(10.0 + cd)


def test_el_mismo_bloqueo_con_otro_numero_de_dias_no_re_dispara():
    """
    "7 días de antigüedad" → "8 días de antigüedad" es EL MISMO bloqueo. Sin la
    normalización, un apagón de Banxico de una semana avisa todos los días.
    """
    cron = Cron()
    cron.previous = dec(0, blockers=[])
    primero = ["inpc_anual: 7 días de antigüedad (límite 5)."]
    assert cron.dia(dec(0, degradada=True, blockers=primero))
    for d in range(1, 15):
        ns = cron.dia(
            dec(d, degradada=True, blockers=[f"inpc_anual: {7 + d} días de antigüedad (límite 5)."])
        )
        assert ns == [], f"día {d}: re-avisó el mismo bloqueo {ns}"
    assert cron.total() == 1


# ============================================================================
# 3. LA HISTÉRESIS NO DEBE OSCILAR
# ============================================================================


def test_un_bloqueo_que_se_va_y_vuelve_no_es_un_bloqueo_nuevo():
    """
    Comparar sólo contra ayer trata como NUEVO a un bloqueo que desapareció y
    regresó. Un apagón intermitente de Banxico es exactamente eso.
    """
    b = ["fix_usdmxn: 7 días de antigüedad (límite 5)."]
    cron = Cron()
    cron.previous = dec(0, blockers=[])
    assert [n.trigger for n in cron.dia(dec(0, degradada=True, blockers=b))] == [
        "BLOCKER_RAISED"
    ]
    cron.dia(dec(1, blockers=[]))                       # se va
    ns = cron.dia(dec(2, degradada=True, blockers=b))   # y vuelve
    assert "BLOCKER_RAISED" not in [n.trigger for n in ns], ns


def test_la_politica_declara_una_banda_de_rearme_menor_que_la_de_entrada():
    p = NotifyPolicy()
    assert 0 < p.hurdle_hysteresis_rearm < p.hurdle_hysteresis_enter


def test_cruzar_el_umbral_de_ida_y_vuelta_no_avisa_en_cada_cruce():
    """
    10.84% → 11.44% → 10.84% → 11.44% ... Doce cruces del umbral de 50 pb.
    Sin banda de re-arme esto serían doce avisos.
    """
    cron = Cron()
    alto, bajo = 0.10843 + 0.0060, 0.10843
    for d in range(13):
        cron.dia(dec(d, hurdle=bajo if d % 2 == 0 else alto))
    assert cron.cuenta("HURDLE_MOVED") <= 1, [n.title for _, n in cron.emitidas]


def test_la_banda_de_rearme_deja_rastro_explicito_en_el_historial():
    """
    El re-arme ocurre en días SIN aviso, así que tiene que persistirse como
    registro `estado`; si no, se pierde entre corridas del cron.
    """
    cron = Cron()
    alto, bajo = 0.10843 + 0.0060, 0.10843
    for d in range(6):
        cron.dia(dec(d, hurdle=bajo if d % 2 == 0 else alto))
    estados = [r for r in cron.history if r.get("kind") == KIND_ESTADO]
    assert estados, "no se persistió el estado de la histéresis"
    assert {"maquina", "ref", "armed", "at"} <= set(estados[-1])
    assert estados[0]["armed"] is False  # desarmado justo después de avisar


def test_una_oscilacion_periodica_de_un_anio_no_es_noticia_recurrente():
    """
    El hurdle rebota entre dos niveles fijos 365 días y termina donde empezó.
    Eso no es información nueva: es la misma noticia repetida. El presupuesto
    anual de avisos operables es 1; aquí se admite el doble por ser MEDIUM.
    """
    cron = Cron()
    alto, bajo = 0.10843 + 0.0060, 0.10843
    for d in range(366):
        cron.dia(dec(d, hurdle=bajo if d % 2 == 0 else alto))
    assert cron.cuenta("HURDLE_MOVED") <= 2, (
        f"{cron.cuenta('HURDLE_MOVED')} avisos de HURDLE_MOVED por una oscilación"
        f" que termina en el mismo nivel"
    )


def test_la_deriva_lenta_del_hurdle_no_puede_ser_invisible():
    """
    Sube 2 pb al día durante un año: 10.84% → 18.14%, +730 pb. Es exactamente el
    movimiento que importa (un ciclo de Banxico completo) y el que ningún salto
    diario delata. El módulo promete avisar "cuánto se movió desde la última vez
    que te avisé"; si la referencia es siempre el día anterior, esto es mudo.
    """
    cron = Cron()
    for d in range(366):
        cron.dia(dec(d, hurdle=0.10843 + 0.0002 * d))
    total_pb = 0.0002 * 365 * 10_000
    assert cron.cuenta("HURDLE_MOVED") >= 1, (
        f"el hurdle se movió {total_pb:.0f} pb en un año y no hubo un solo aviso"
    )


def test_la_referencia_de_histeresis_se_ancla_desde_la_primera_comparacion():
    """
    Sin ancla persistida, la referencia vuelve a ser "ayer" en cada corrida y el
    trigger mide el salto DIARIO en vez del acumulado desde el último aviso.
    """
    cron = Cron()
    cron.dia(dec(0, hurdle=0.10843))                       # primera corrida: silencio
    assert cron.dia(dec(1, hurdle=0.10843 + 0.0002)) == []  # 2 pb: no es noticia
    estados = [r for r in cron.history if r.get("kind") == KIND_ESTADO]
    assert estados, "la referencia no quedó anclada en el historial"
    assert estados[0]["ref"] == pytest.approx(0.10843)
    assert estados[0]["armed"] is True


def test_un_salto_grande_y_monotono_si_re_arma_el_trigger():
    """El escape de runaway: un movimiento que nunca regresa no puede dejar mudo
    al trigger para siempre."""
    cron = Cron()
    cron.dia(dec(0, hurdle=0.10843))
    cron.dia(dec(1, hurdle=0.10843 + 0.0060))          # dispara, deja desarmado
    assert cron.cuenta("HURDLE_MOVED") == 1
    for d in range(2, 60):
        cron.dia(dec(d, hurdle=0.10843 + 0.0060 + 0.0004 * (d - 1)))
    assert cron.cuenta("HURDLE_MOVED") >= 2


def test_la_materialidad_no_alterna_todos_los_dias():
    """El veredicto de materialidad es binario: sin cooldown flapearía a diario."""
    cron = Cron()
    for d in range(120):
        cron.dia(dec(d, materialidad="MATERIAL" if d % 2 == 0 else "INMATERIAL"))
    assert cron.cuenta("MATERIALITY_FLIPPED") <= 120 / 30 + 1


# ============================================================================
# 4. EL PRESUPUESTO ANUAL MANDA — el test más importante del archivo
# ============================================================================


def _anio_adversarial(cron: Cron, dias: int = 366) -> Cron:
    """
    Entrada diseñada para arrancarle al motor tantos avisos como sea posible:
    la acción cambia todos los días, los bloqueos entran y salen con textos
    distintos, el hurdle rebota 60 pb, el presupuesto cruza 1.0 en los dos
    sentidos, la materialidad alterna y el régimen rota.
    """
    bloqueos = [
        "fix_usdmxn: 7 días de antigüedad (límite 5).",
        "cetes_28: 9 días de antigüedad (límite 5).",
        "inpc_anual: 12 días de antigüedad (límite 5).",
        "Pata más chica: 3.10 USD vs mínimo 10.00 USD (POR DEBAJO DEL MÍNIMO).",
        "Presupuesto de comisiones agotado: quedan 0.4 operaciones completas.",
    ]
    regs = [["NEUTRAL", "RISK_OFF"], ["RISK_ON", "NEUTRAL"], ["RISK_OFF", "STRESS"]]
    for d in range(dias):
        cron.dia(
            dec(
                d,
                action=OPERABLES[d % len(OPERABLES)],
                blockers=[bloqueos[d % len(bloqueos)]] if d % 2 == 0 else [],
                hurdle=0.10843 + (0.0060 if d % 2 else 0.0),
                round_trips=0.4 if d % 2 else 1.4,
                materialidad="MATERIAL" if d % 2 else "INMATERIAL",
                regimenes=regs[d % 3],
            )
        )
    return cron


def test_un_anio_adversarial_no_supera_el_presupuesto_de_ordenes_ejecutables():
    """
    LA prueba del módulo. 366 evaluaciones diarias con entrada hostil contra un
    presupuesto de comisiones que paga 1.67 round-trips al año.

    Lo que se cuenta es el CONTENIDO, no el nombre del trigger: un aviso cuesta
    presupuesto si te manda mover dinero, se llame ACTION_CHANGED o
    MATERIALITY_FLIPPED. Un ACTION_CHANGED hacia STAY_IN_CETES o HOLD_NO_ACTION
    dice "no operes" y no gasta nada.
    """
    cron = _anio_adversarial(Cron())
    permitidos = NotifyPolicy().max_action_changes(COSTOS)
    assert permitidos == 1, permitidos
    marcadas = [n for _, n in cron.emitidas if n.es_orden_ejecutable]
    assert len(marcadas) <= permitidos, (
        f"{len(marcadas)} avisos con orden ejecutable en un año contra"
        f" {MAX_ROUND_TRIPS:.2f} round-trips pagables:"
        f" {[n.trigger for n in marcadas]}"
    )


def test_el_campo_es_orden_ejecutable_coincide_con_el_texto():
    """La bandera contra la que se cobra el presupuesto no puede mentirle al
    texto que lee el usuario: si dice "Mover N MXN", está marcada."""
    cron = _anio_adversarial(Cron())
    for _, n in cron.emitidas:
        tiene_orden = any(_ORDEN_EJECUTABLE.search(t) for t in n.estrategia)
        assert tiene_orden == n.es_orden_ejecutable, (n.trigger, n.estrategia)


def test_los_avisos_de_cambio_de_accion_sin_orden_siguen_acotados():
    """
    Un ACTION_CHANGED que no cuesta comisiones sigue siendo prioridad alta y por
    lo tanto está limitado por el cupo de esa clase, no por el presupuesto anual.
    """
    cron = _anio_adversarial(Cron())
    p = NotifyPolicy()
    techo = 13 * p.max_high_per_30d  # ventanas de 30 días en 366
    assert cron.cuenta("ACTION_CHANGED") <= techo, cron.cuenta("ACTION_CHANGED")


def test_un_anio_adversarial_no_emite_mas_ordenes_ejecutables_que_round_trips():
    """
    ACTION_CHANGED no es el único aviso que te manda mover dinero: BLOCKER_CLEARED
    y MATERIALITY_FLIPPED también embeben el plan operativo ("Mover 2,880 MXN de
    CETES 364d a cripto"). Lo que tiene que estar acotado es el número de avisos
    que contienen una ORDEN, no el nombre del trigger.
    """
    # Escenario que maximiza avisos con plan ejecutable: el bloqueo entra y sale
    # cada 8 días, así que el motor alterna entre "bloqueado" y "opera esto".
    cron = Cron()
    for d in range(366):
        if (d // 8) % 2 == 0:
            cron.dia(
                dec(
                    d,
                    action="BLOCKED_BELOW_MIN_NOTIONAL",
                    blockers=[f"Pata más chica: {d}.10 USD vs mínimo 10.00 USD."],
                )
            )
        else:
            cron.dia(dec(d, action="ALLOCATE_TO_CRYPTO", blockers=[]))

    ordenes = cron.ordenes_ejecutables()
    techo = math.ceil(MAX_ROUND_TRIPS)  # 2
    assert len(ordenes) <= techo, (
        f"{len(ordenes)} avisos con orden ejecutable en un año contra"
        f" {MAX_ROUND_TRIPS:.2f} round-trips pagables:"
        f" {[n.trigger for n in ordenes][:6]}"
    )


def test_un_anio_adversarial_respeta_el_tope_rodante_de_30_dias():
    """
    Invariante 2 del propio módulo: "ni el sistema puede emitir más de
    `max_per_30d` avisos en 30 días".
    """
    cron = _anio_adversarial(Cron())
    tope = NotifyPolicy().max_per_30d
    peor = cron.peor_ventana(NotifyPolicy().rolling_window_days)
    assert peor <= tope, f"{peor} avisos en una ventana de 30 días contra un tope de {tope}"


def test_un_anio_adversarial_no_convierte_el_motor_en_una_app_que_habla_diario():
    """
    Cota gruesa de cordura: un motor que sólo puede pagar ~1.7 operaciones al año
    no puede entregar cientos de avisos al año, sea cual sea su prioridad.
    """
    cron = _anio_adversarial(Cron())
    assert cron.total() <= 12 * NotifyPolicy().max_per_30d, (
        f"{cron.total()} notificaciones en 366 evaluaciones"
        f" ({cron.total() / 366:.2f} por día)"
    )


def test_el_presupuesto_de_avisos_se_deriva_del_de_comisiones_y_trunca_hacia_abajo():
    """1.67 round-trips son 1 aviso operable, no 2. Redondear a favor de operar
    es exactamente el error que este repo existe para evitar."""
    p = NotifyPolicy()
    assert p.max_action_changes_per_year is None       # derivado, no configurado
    assert p.max_action_changes(COSTOS) == math.floor(MAX_ROUND_TRIPS)
    assert p.max_action_changes(None) == 1             # piso defendible sin presupuesto
    assert p.max_action_changes({"max_round_trips_per_year": 0.2}) == 1
    assert p.max_action_changes({"max_round_trips_per_year": 9.9}) == 9


def test_la_meta_notificacion_de_sobreoperacion_nunca_dice_opera_mas():
    """Si el motor detecta exceso de señal, la respuesta es revisar la política."""
    cron = Cron()
    cron.previous = dec(0, action="STAY_IN_CETES")
    cron.dia(dec(0, action="ALLOCATE_TO_CRYPTO"))
    cron.previous = dec(20, action="ALLOCATE_TO_CRYPTO")
    ns = cron.dia(dec(20, action="REDUCE_CRYPTO"))
    meta = [n for n in ns if n.trigger == "OVERTRADING_DETECTED"]
    assert meta, [n.trigger for n in ns]
    assert not any(_ORDEN_EJECUTABLE.search(t) for t in meta[0].estrategia)
    assert "No operes" in " ".join(meta[0].estrategia)
    # y el ACTION_CHANGED que la provocó no salió
    assert "ACTION_CHANGED" not in [n.trigger for n in ns]


# ============================================================================
# 5. LA PRIORIDAD NO SE PUEDE GAMEAR
# ============================================================================


def _relleno(trigger: str, n: int, desde: float) -> list[dict[str, Any]]:
    return [
        {
            "kind": KIND_NOTIFICACION,
            "trigger": trigger,
            "priority": PRIORIDAD_POR_TRIGGER[trigger],
            "title": f"relleno {i}",
            "dedup_key": f"{trigger}:relleno-{i}",
            "fired_at": (T0 + timedelta(days=desde + i * 0.5)).isoformat(),
        }
        for i in range(n)
    ]


def test_una_inundacion_de_medium_no_puede_tapar_un_bloqueo_nuevo():
    historial = _relleno("REGIME_FLIPPED", 40, 30.0)
    ns = evaluate(
        dec(60, blockers=["nuevo: 9 días de antigüedad (límite 5)."]),
        dec(60, blockers=[]),
        historial,
        NotifyPolicy(),
        COSTOS,
    )
    assert [n.trigger for n in ns] == ["BLOCKER_RAISED"]
    assert ns[0].priority == "HIGH"


def test_una_inundacion_de_medium_no_puede_tapar_el_presupuesto_agotado():
    historial = _relleno("MATERIALITY_FLIPPED", 40, 30.0)
    ns = evaluate(
        dec(60, round_trips=0.4),
        dec(60, round_trips=1.4),
        historial,
        NotifyPolicy(),
        COSTOS,
    )
    assert "FEE_BUDGET_LOW" in [n.trigger for n in ns]


def test_el_tope_rodante_se_gasta_en_orden_de_urgencia():
    """Si algo se cae por el tope, que se caiga lo menos urgente."""
    historial = _relleno("REGIME_FLIPPED", 3, 30.0)
    ns = evaluate(
        dec(
            60,
            action="REDUCE_CRYPTO",
            blockers=["nuevo: 9 días de antigüedad (límite 5)."],
            hurdle=0.10843 + 0.0060,
            materialidad="INMATERIAL",
        ),
        dec(60, action="ALLOCATE_TO_CRYPTO", blockers=[], materialidad="MATERIAL"),
        historial,
        NotifyPolicy(),
        COSTOS,
    )
    prioridades = [n.priority for n in ns]
    assert prioridades == sorted(prioridades, key=lambda p: ("HIGH", "MEDIUM", "INFO").index(p))
    entregados = [n.trigger for n in ns]
    assert "BLOCKER_RAISED" in entregados


def test_high_no_puede_saltarse_el_tope_global_indefinidamente():
    """
    Contraparte del test anterior. Que un HIGH pase por encima del tope es
    correcto una vez; que pase TODOS LOS DÍAS convierte la excepción en el
    canal normal y destruye el valor de la prioridad alta.

    Adversario realista: un apagón intermitente de Banxico que levanta un
    bloqueo distinto cada día (todos HIGH, todos con cooldown de 1 día).
    """
    cron = Cron()
    for d in range(366):
        b = [f"serie_{d % 7}: 9 días de antigüedad (límite 5)."]
        cron.dia(dec(d, degradada=True, blockers=b))
    p = NotifyPolicy()
    tope_anual = 13 * p.max_high_per_30d  # ventanas de 30 días que caben en 366
    assert cron.cuenta("BLOCKER_RAISED") <= tope_anual, (
        f"{cron.cuenta('BLOCKER_RAISED')} avisos HIGH en un año; el cupo es"
        f" {p.max_high_per_30d} por {p.rolling_window_days} días"
    )


def test_lo_que_se_cae_por_cupo_de_high_se_resume_en_vez_de_perderse():
    """
    Descartar en silencio un bloqueo que parpadea le esconde al usuario el único
    dato que importa de esa situación: que la fuente está inestable.
    """
    cron = Cron()
    for d in range(40):
        b = [f"serie_{d % 7}: 9 días de antigüedad (límite 5)."]
        cron.dia(dec(d, degradada=True, blockers=b))

    p = NotifyPolicy()
    assert cron.cuenta("BLOCKER_RAISED") <= 2 * p.max_high_per_30d
    resumenes = [n for _, n in cron.emitidas if n.trigger == "FLAPPING_DETECTED"]
    assert resumenes, "los HIGH descartados desaparecieron sin dejar rastro visible"

    n = resumenes[0]
    assert n.priority != "HIGH"                      # el resumen no puede ser el ruido
    assert not n.es_orden_ejecutable                 # ni puede pedir operar
    assert re.search(r"\d+ veces en los últimos \d+ días", " ".join(n.razonamiento))
    assert _NO_OPERAR.search(" ".join(n.estrategia))


def test_el_resumen_de_intermitencia_tambien_tiene_cooldown():
    """Si el meta-aviso de "esto parpadea" parpadeara, no habríamos arreglado nada."""
    cron = Cron()
    for d in range(120):
        b = [f"serie_{d % 7}: 9 días de antigüedad (límite 5)."]
        cron.dia(dec(d, degradada=True, blockers=b))
    cd = NotifyPolicy().cooldown_for("FLAPPING_DETECTED")
    assert cron.cuenta("FLAPPING_DETECTED") <= 120 / cd + 1


def test_la_reserva_de_prioridad_baja_sobrevive_a_un_aluvion_de_high():
    """
    Con bloqueos entrando todos los días, un cambio real de hurdle tiene que
    seguir llegando: para eso existe el cupo reservado.
    """
    cron = Cron()
    for d in range(90):
        cron.dia(
            dec(
                d,
                blockers=[f"serie_{d % 7}: 9 días de antigüedad (límite 5)."],
                hurdle=0.10843 + 0.0020 * d,
            )
        )
    assert cron.cuenta("HURDLE_MOVED") >= 1, (
        "el aluvión de HIGH volvió a dejar mudos a los avisos de prioridad baja"
    )


def test_una_politica_con_cupos_imposibles_no_se_puede_construir():
    """Regla 6: una restricción se expresa como bloqueo duro, no como advertencia."""
    with pytest.raises(ValueError):
        NotifyPolicy(max_per_30d=4, max_high_per_30d=4, medium_reserve_per_30d=2)
    with pytest.raises(ValueError):
        NotifyPolicy(medium_reserve_per_30d=0)
    p = NotifyPolicy()
    assert p.cupo_alto() + p.cupo_bajo() == p.max_per_30d
    assert p.cupo_bajo() >= p.medium_reserve_per_30d


def test_el_tope_solo_puede_callar_a_un_medium_si_el_propio_tope_se_respeta():
    """
    El tope rodante cuenta TODOS los avisos entregados, pero HIGH nunca se
    descarta: un flujo de HIGH deja `restantes` permanentemente negativo y ahoga
    a los MEDIUM legítimos (hurdle, materialidad) durante todo el año.

    Invocar el tope para callar a alguien exige haberlo respetado uno mismo.
    """
    cron = Cron()
    for d in range(366):
        cron.dia(
            dec(
                d,
                degradada=(d % 2 == 0),
                blockers=[f"serie_{d % 7}: 9 días de antigüedad (límite 5)."] if d % 2 == 0 else [],
                hurdle=0.10843 + 0.0002 * d,
                materialidad="MATERIAL" if (d // 45) % 2 else "INMATERIAL",
            )
        )
    tope = NotifyPolicy().max_per_30d
    ahogados = [
        r for r in cron.suprimidas if r["motivo"] == "tope_30d" and r["priority"] == "MEDIUM"
    ]
    altos = sum(1 for _, n in cron.emitidas if n.priority == "HIGH")
    if ahogados:
        assert cron.peor_ventana(NotifyPolicy().rolling_window_days) <= tope, (
            f"{len(ahogados)} avisos MEDIUM descartados por 'tope_30d' mientras el motor"
            f" entregaba {cron.peor_ventana(30)} avisos en 30 días (tope {tope}) y"
            f" {altos} HIGH en el año"
        )


def test_toda_prioridad_declarada_es_alcanzable():
    """Una prioridad que ningún trigger puede producir es configuración muerta:
    o se usa o se borra, pero no se documenta como si existiera."""
    usadas = set(PRIORIDAD_POR_TRIGGER.values())
    assert usadas == set(notify_mod.PRIORIDADES)


def test_todo_trigger_declarado_tiene_prioridad_y_orden():
    assert set(PRIORIDAD_POR_TRIGGER) == set(TRIGGERS)
    assert len(set(TRIGGERS)) == len(TRIGGERS)
    for t in TRIGGERS:
        assert NotifyPolicy().cooldown_for(t) > 0


# ============================================================================
# 6. IDEMPOTENCIA Y ESTADO
# ============================================================================


def _historial_realista() -> list[dict[str, Any]]:
    return [
        {
            "kind": KIND_NOTIFICACION,
            "trigger": "HURDLE_MOVED",
            "priority": "MEDIUM",
            "title": "Hurdle 10.20% → 10.84%",
            "dedup_key": "HURDLE_MOVED:1020->1084",
            "fired_at": (T0 - timedelta(days=40)).isoformat(),
            "changed_to": {"hurdle_total_anualizado": 0.10843},
        },
        {"kind": KIND_ESTADO, "maquina": "HURDLE_MOVED", "ref": 0.10843, "armed": False,
         "at": (T0 - timedelta(days=40)).isoformat()},
        {"kind": KIND_SUPRESION, "trigger": "REGIME_FLIPPED", "priority": "MEDIUM",
         "title": "x", "dedup_key": "y", "motivo": "cooldown", "detalle": "z",
         "at": (T0 - timedelta(days=3)).isoformat()},
    ]


def test_evaluar_dos_veces_con_la_misma_entrada_da_el_mismo_resultado():
    hist = _historial_realista()
    prev = dec(0, action="STAY_IN_CETES", materialidad="MATERIAL")
    cur = dec(1, action="ALLOCATE_TO_CRYPTO", materialidad="INMATERIAL",
              blockers=["a: 9 días de antigüedad (límite 5).", "b: 4 días (límite 2)."])
    a_ns, a_aud = evaluate_with_audit(cur, prev, hist, NotifyPolicy(), COSTOS)
    b_ns, b_aud = evaluate_with_audit(cur, prev, hist, NotifyPolicy(), COSTOS)
    assert [n.to_dict() for n in a_ns] == [n.to_dict() for n in b_ns]
    assert a_aud == b_aud
    assert a_ns, "el escenario tiene que producir algo para que la prueba sirva"


def test_evaluate_no_muta_el_historial_que_recibe():
    hist = _historial_realista()
    copia = copy.deepcopy(hist)
    cur = dec(1, action="REDUCE_CRYPTO", blockers=["a: 9 días de antigüedad (límite 5)."])
    evaluate_with_audit(cur, dec(0), hist, NotifyPolicy(), COSTOS)
    assert hist == copia, "el historial de entrada se modificó en sitio"
    assert len(hist) == len(copia)


def test_evaluate_no_muta_las_decisions_que_recibe():
    prev, cur = dec(0), dec(1, action="REDUCE_CRYPTO")
    p_copia, c_copia = copy.deepcopy(prev), copy.deepcopy(cur)
    evaluate_with_audit(cur, prev, [], NotifyPolicy(), COSTOS)
    assert prev.to_json_dict() == p_copia.to_json_dict()
    assert cur.to_json_dict() == c_copia.to_json_dict()


def test_los_registros_hacen_round_trip_por_json():
    cron = _anio_adversarial(Cron(), dias=90)
    crudo = json.dumps(cron.history, ensure_ascii=False)
    assert json.loads(crudo) == cron.history
    for _, n in cron.emitidas:
        r = n.to_record()
        assert r["kind"] == KIND_NOTIFICACION
        assert json.loads(json.dumps(r, ensure_ascii=False)) == r


def test_los_registros_de_supresion_explican_por_que_se_callo():
    cron = _anio_adversarial(Cron(), dias=90)
    assert cron.suprimidas
    for r in cron.suprimidas:
        assert r["motivo"] in (
            "cooldown", "dedup", "tope_30d", "presupuesto_anual_de_acciones",
        )
        assert r["detalle"].strip()
        assert r["trigger"] in TRIGGERS


def test_el_orden_de_los_bloqueos_no_cambia_la_llave_de_dedup():
    """Los conjuntos de Python no tienen orden estable entre procesos; si el
    dedup_key dependiera de él, el anti-spam se caería al azar."""
    bs = ["a: 9 días de antigüedad (límite 5).", "b: 3 días de antigüedad (límite 1)."]
    k1 = evaluate(dec(1, blockers=bs), dec(0, blockers=[]), [], NotifyPolicy(), COSTOS)[0]
    k2 = evaluate(dec(1, blockers=bs[::-1]), dec(0, blockers=[]), [], NotifyPolicy(), COSTOS)[0]
    assert k1.dedup_key == k2.dedup_key
    # El texto que lee el usuario tampoco puede depender del orden de entrada.
    assert (k1.title, k1.body, k1.razonamiento, k1.estrategia) == (
        k2.title, k2.body, k2.razonamiento, k2.estrategia,
    )


# ============================================================================
# 7. INTEGRIDAD DEL CONTENIDO
# ============================================================================


def _una_de_cada_trigger() -> list[Notification]:
    """Un ejemplar de cada trigger emitible, cada uno con historial limpio."""
    p = NotifyPolicy()
    casos: list[tuple[Decision, Decision, list[dict[str, Any]]]] = [
        (dec(0, action="STAY_IN_CETES"), dec(1, action="ALLOCATE_TO_CRYPTO"), []),
        (dec(0, action="ALLOCATE_TO_CRYPTO"), dec(1, action="REDUCE_CRYPTO"), []),
        (dec(0, action="REDUCE_CRYPTO"), dec(1, action="HOLD_NO_ACTION"), []),
        (dec(0, blockers=[]), dec(1, blockers=["a: 9 días de antigüedad (límite 5)."]), []),
        (dec(0, blockers=["a: 9 días de antigüedad (límite 5)."]), dec(1, blockers=[]), []),
        (dec(0, round_trips=1.4), dec(1, round_trips=0.4), []),
        (dec(0, regimenes=["NEUTRAL", "NEUTRAL"]), dec(1, regimenes=["STRESS", "RISK_OFF"]), []),
        (dec(0, hurdle=0.10843), dec(1, hurdle=0.10843 + 0.0080), []),
        (dec(0, hurdle=0.10843), dec(1, hurdle=0.10843 - 0.0080), []),
        (dec(0, materialidad="INMATERIAL"), dec(1, materialidad="MATERIAL"), []),
        (dec(0, materialidad="MATERIAL"), dec(1, materialidad="INMATERIAL"), []),
    ]
    out: list[Notification] = []
    for prev, cur, hist in casos:
        out += evaluate(cur, prev, hist, p, COSTOS)
    # la meta-notificación necesita presupuesto agotado
    hist = [
        {"kind": KIND_NOTIFICACION, "trigger": "ACTION_CHANGED", "priority": "HIGH",
         "dedup_key": "ACTION_CHANGED:A->B", "fired_at": (T0 - timedelta(days=30)).isoformat(),
         "es_orden_ejecutable": True}
    ]
    out += evaluate(
        dec(1, action="REDUCE_CRYPTO"), dec(0, action="ALLOCATE_TO_CRYPTO"), hist, p, COSTOS
    )
    # el resumen de intermitencia necesita el cupo de HIGH agotado dentro de la
    # ventana rodante, pero fuera del cooldown del propio trigger
    hist = _relleno("BLOCKER_RAISED", p.max_high_per_30d, -25.0)
    out += evaluate(
        dec(1, blockers=["z: 9 días de antigüedad (límite 5)."]), dec(0, blockers=[]),
        hist, p, COSTOS,
    )
    return out


def test_el_barrido_cubre_todos_los_triggers():
    vistos = {n.trigger for n in _una_de_cada_trigger()}
    assert vistos == set(TRIGGERS), sorted(set(TRIGGERS) - vistos)


def test_ninguna_notificacion_sale_sin_razonamiento_ni_estrategia():
    for n in _una_de_cada_trigger():
        assert n.razonamiento, n.trigger
        assert n.estrategia, n.trigger
        assert all(r.strip() for r in n.razonamiento), n.trigger
        assert all(e.strip() for e in n.estrategia), n.trigger


def test_toda_estrategia_dice_si_hay_que_operar_hoy_o_no():
    """
    Un aviso ambiguo obliga a abrir la app a las 11 de la noche, y eso se traduce
    en operar sin leer. Cada notificación tiene que resolver la única pregunta
    que importa: ¿muevo dinero hoy, sí o no?
    """
    for n in _una_de_cada_trigger():
        junto = " ".join(n.estrategia)
        opera = bool(_ORDEN_EJECUTABLE.search(junto))
        no_opera = bool(_NO_OPERAR.search(junto))
        assert opera or no_opera, f"{n.trigger}: {junto[:160]}"
        assert len(n.estrategia) >= 2, n.trigger


def test_ningun_texto_visible_filtra_repr_none_nan_ni_floats_crudos():
    for n in _una_de_cada_trigger():
        m = _BASURA.search(texto(n))
        assert m is None, f"{n.trigger}: {m.group(0)!r} en el texto visible"


def test_el_titulo_cabe_en_la_pantalla_de_bloqueo():
    for n in _una_de_cada_trigger():
        assert 0 < len(n.title) <= MAX_TITULO, (len(n.title), n.title)


def test_una_notificacion_sin_estrategia_no_se_construye():
    """Validación dura, no advertencia (regla 6)."""
    with pytest.raises(ValueError):
        Notification("ACTION_CHANGED", "HIGH", "t", "b", ["r"], [], {}, {}, T0.isoformat(), "k")
    with pytest.raises(ValueError):
        Notification("NO_EXISTE", "HIGH", "t", "b", ["r"], ["e"], {}, {}, T0.isoformat(), "k")
    with pytest.raises(ValueError):
        Notification("ACTION_CHANGED", "URGENTÍSIMO", "t", "b", ["r"], ["e"], {}, {},
                     T0.isoformat(), "k")
    with pytest.raises(ValueError):
        Notification("ACTION_CHANGED", "HIGH", "T" * (MAX_TITULO + 1), "b", ["r"], ["e"], {}, {},
                     T0.isoformat(), "k")


def test_todo_aviso_operable_declara_su_invalidacion_con_numeros():
    """Regla del módulo: toda estrategia dice qué la invalida, con números."""
    for n in _una_de_cada_trigger():
        if n.trigger in ("BLOCKER_RAISED", "FEE_BUDGET_LOW", "OVERTRADING_DETECTED"):
            continue  # su invalidación es cualitativa y está redactada aparte
        assert any("INVALIDACIÓN" in e for e in n.estrategia), n.trigger


def test_un_hurdle_corrupto_no_se_publica_como_texto():
    """
    NaN/inf en el snapshot es un dato roto, no un dato. Regla 4: bloquea, no
    degrada. Lo que no puede pasar es que llegue al teléfono como "nan%".
    """
    for malo in (float("nan"), float("inf")):
        ns = evaluate(
            dec(1, action="REDUCE_CRYPTO", hurdle=malo),
            dec(0, action="ALLOCATE_TO_CRYPTO"),
            [],
            NotifyPolicy(),
            COSTOS,
        )
        for n in ns:
            m = _BASURA.search(texto(n))
            assert m is None, f"hurdle={malo}: {n.trigger} publicó {m.group(0)!r}"


def test_el_render_de_ntfy_no_pierde_el_razonamiento():
    for n in _una_de_cada_trigger():
        p = render_ntfy(n)
        assert p["headers"]["Title"] == n.title
        for r in n.razonamiento:
            assert r in p["body"]
        for e in n.estrategia:
            assert e in p["body"]
        json.dumps(p, ensure_ascii=False)


def test_el_markdown_dice_cuantos_avisos_cuestan_comisiones():
    """Es el único número por el que vale la pena abrir la app hoy."""
    con_orden = evaluate(
        dec(1, action="ALLOCATE_TO_CRYPTO"), dec(0, action="STAY_IN_CETES"),
        [], NotifyPolicy(), COSTOS,
    )
    assert con_orden and con_orden[0].es_orden_ejecutable
    assert "1 de ellos contiene una orden que cuesta comisiones" in render_markdown(con_orden)

    sin_orden = evaluate(
        dec(1, hurdle=0.10843 + 0.0080), dec(0, hurdle=0.10843), [], NotifyPolicy(), COSTOS
    )
    assert sin_orden and not any(n.es_orden_ejecutable for n in sin_orden)
    assert "Ninguno contiene una orden" in render_markdown(sin_orden)


def test_el_dia_sin_avisos_se_distingue_de_un_paso_que_falló():
    md = render_markdown([])
    assert "Sin cambios de estado" in md
    assert "silencio" in md.lower()


def test_los_sinks_no_tocan_la_red():
    """CLAUDE.md: cero red en el motor y cero tests que peguen a una API."""
    for mod in (notify_mod, sinks_mod):
        src = inspect.getsource(mod)
        assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests)", src, re.M), mod
        assert "urlopen" not in src


# ============================================================================
# 8. ENTRADA DEGRADADA
# ============================================================================


def test_datos_rancios_no_truenan_el_notificador():
    prev = dec(0, action="ALLOCATE_TO_CRYPTO")
    cur = dec(1, degradada=True, blockers=["inpc_anual: 221 días de antigüedad (límite 5)."])
    assert cur.hurdle == {} and cur.sizing == {} and cur.costs == {}
    assert cur.required_returns == {}
    ns = evaluate(cur, prev, [], NotifyPolicy(), COSTOS)
    assert [n.trigger for n in ns] == ["BLOCKER_RAISED"]


def test_bajo_datos_rancios_no_se_cita_ningun_numero_del_snapshot():
    """
    Con hurdle/sizing/costs vacíos, cualquier cifra que aparezca en el aviso está
    inventada o es de ayer. Regla 4: bloquean, no degradan.
    """
    prev = dec(0, action="ALLOCATE_TO_CRYPTO")
    cur = dec(1, degradada=True, blockers=["inpc_anual: 221 días de antigüedad (límite 5)."])
    for n in evaluate(cur, prev, [], NotifyPolicy(), COSTOS):
        cuerpo = " \n".join([n.body, *n.estrategia])
        assert "MXN" not in cuerpo, n.trigger
        assert not re.search(r"\d+\.\d+%", cuerpo), n.trigger
        assert "INVALIDACIÓN: si antes de ejecutar el hurdle" not in " ".join(n.estrategia)


def test_bajo_datos_rancios_no_se_dispara_ningun_trigger_numerico():
    """Comparar contra huecos produce avisos falsos: hurdle, régimen,
    materialidad y presupuesto tienen que quedarse callados."""
    prev = dec(0, action="ALLOCATE_TO_CRYPTO", hurdle=0.20, materialidad="MATERIAL",
               round_trips=1.4, regimenes=["RISK_ON", "RISK_ON"])
    cur = dec(1, degradada=True, blockers=["x: 9 días de antigüedad (límite 5)."])
    triggers = {n.trigger for n in evaluate(cur, prev, [], NotifyPolicy(), COSTOS)}
    assert triggers <= {"BLOCKER_RAISED"}


def test_entrar_a_datos_rancios_no_cuenta_como_cambio_de_accion():
    """Un apagón de Banxico no es una decisión de inversión: no puede gastar el
    presupuesto anual de avisos operables."""
    prev = dec(0, action="ALLOCATE_TO_CRYPTO")
    cur = dec(1, degradada=True, blockers=["x: 9 días de antigüedad (límite 5)."])
    ns = evaluate(cur, prev, [], NotifyPolicy(), COSTOS)
    assert "ACTION_CHANGED" not in [n.trigger for n in ns]


def test_salir_de_datos_rancios_no_truena_ni_inventa_comparaciones():
    """El previo tiene hurdle/sizing/costs vacíos: comparar contra eso no puede
    producir un HURDLE_MOVED ni un FEE_BUDGET_LOW."""
    prev = dec(0, degradada=True, blockers=["x: 9 días de antigüedad (límite 5)."])
    cur = dec(1, action="ALLOCATE_TO_CRYPTO", blockers=[])
    ns = evaluate(cur, prev, [], NotifyPolicy(), COSTOS)
    assert [n.trigger for n in ns] == ["BLOCKER_CLEARED"]
    assert "No es una señal de compra" in ns[0].body or "NO es una señal" in ns[0].body


def test_dos_dias_seguidos_de_datos_rancios_son_silencio():
    cron = Cron()
    b = ["x: 9 días de antigüedad (límite 5)."]
    cron.previous = dec(0, action="ALLOCATE_TO_CRYPTO")
    assert len(cron.dia(dec(0, degradada=True, blockers=b))) == 1
    assert cron.dia(dec(1, degradada=True, blockers=b)) == []
    assert cron.dia(dec(2, degradada=True, blockers=b)) == []


def test_decision_sin_costos_no_truena_el_presupuesto_de_acciones():
    """El CLI le pasa `d.costs`; bajo bloqueo es un dict vacío."""
    p = NotifyPolicy()
    assert p.max_action_changes({}) == 1
    ns = evaluate(
        dec(1, action="REDUCE_CRYPTO"), dec(0, action="ALLOCATE_TO_CRYPTO"), [], p, {}
    )
    assert [n.trigger for n in ns] == ["ACTION_CHANGED"]


# ============================================================================
# 9. SCHEMA
# ============================================================================


def _escribe_previo(tmp_path: Path, data: dict[str, Any]) -> Path:
    (tmp_path / "latest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_schema_mayor_distinto_no_produce_notificaciones(tmp_path, capsys):
    from inversor.__main__ import _load_previous_decision

    viejo = dec(0, action="STAY_IN_CETES").to_json_dict()
    viejo["schema_version"] = "1.4.0"
    _escribe_previo(tmp_path, viejo)

    actual = dec(1, action="ALLOCATE_TO_CRYPTO")
    previo = _load_previous_decision(tmp_path, actual)
    assert previo is None
    assert "no es comparable" in capsys.readouterr().err
    assert evaluate(actual, previo, [], NotifyPolicy(), COSTOS) == []


def test_sin_snapshot_previo_el_cargador_devuelve_none(tmp_path):
    from inversor.__main__ import _load_previous_decision

    assert _load_previous_decision(tmp_path, dec(0)) is None


def test_mismo_mayor_si_es_comparable(tmp_path):
    from inversor.__main__ import _load_previous_decision

    viejo = dec(0, action="STAY_IN_CETES").to_json_dict()
    viejo["schema_version"] = _BASE.schema_version
    _escribe_previo(tmp_path, viejo)
    previo = _load_previous_decision(tmp_path, dec(1, action="ALLOCATE_TO_CRYPTO"))
    assert isinstance(previo, Decision)
    assert previo.action == "STAY_IN_CETES"


def test_un_campo_nuevo_con_el_mismo_mayor_no_debe_tronar(tmp_path):
    """
    Contrato engine → Android de CLAUDE.md: "Campos nuevos: permitidos sin subir
    versión mayor". Un snapshot escrito por una versión menor más nueva tiene que
    poder leerse; si truena, el cron del día se cae entero por un campo aditivo.
    """
    from inversor.__main__ import _load_previous_decision

    viejo = dec(0, action="STAY_IN_CETES").to_json_dict()
    mayor = _BASE.schema_version.split(".")[0]
    viejo["schema_version"] = f"{mayor}.9.0"
    viejo["campo_aditivo_nuevo"] = {"lo_que_sea": 1}
    _escribe_previo(tmp_path, viejo)

    previo = _load_previous_decision(tmp_path, dec(1, action="ALLOCATE_TO_CRYPTO"))
    assert previo is None or isinstance(previo, Decision)


def test_un_campo_que_desaparece_con_el_mismo_mayor_si_truena(tmp_path):
    """
    El caso contrario NO es aditivo: quitar un campo cambia el significado de la
    comparación campo a campo y exige subir el mayor. Regla de estilo del repo:
    nada de try/except que se trague el error; si algo falla, truena fuerte.
    """
    from inversor.__main__ import _load_previous_decision

    viejo = dec(0, action="STAY_IN_CETES").to_json_dict()
    del viejo["hurdle"]
    _escribe_previo(tmp_path, viejo)
    with pytest.raises(ValueError, match="SCHEMA_VERSION"):
        _load_previous_decision(tmp_path, dec(1))


# ============================================================================
# 10. EL SNAPSHOT REAL DEL REPO
# ============================================================================


def _latest() -> dict[str, Any] | None:
    p = REPO / "snapshots" / "latest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def test_el_snapshot_publicado_es_evaluable_y_callado_contra_si_mismo():
    data = _latest()
    if data is None:
        pytest.skip("no hay snapshots/latest.json en el árbol")
    ayer = Decision(**data)
    hoy = Decision(**data)
    hoy.generated_at = (notify_mod._parse_iso(ayer.generated_at) + timedelta(days=1)).isoformat()
    assert evaluate(hoy, ayer, [], NotifyPolicy(), data["costs"]) == []


def test_el_presupuesto_del_snapshot_publicado_paga_menos_de_dos_operaciones():
    """Si esto deja de ser cierto, todos los topes de este archivo cambian."""
    data = _latest()
    if data is None:
        pytest.skip("no hay snapshots/latest.json en el árbol")
    assert data["costs"]["max_round_trips_per_year"] < 2.0
    assert NotifyPolicy().max_action_changes(data["costs"]) == 1
