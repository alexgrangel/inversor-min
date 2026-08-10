"""
Notificaciones por CAMBIO DE ESTADO. No por "oportunidad".

El usuario pidió avisos de "los mejores momentos para invertir". A este tamaño
de cuenta esa pregunta no tiene respuesta honesta: el presupuesto de comisiones
autoriza ~1.7 round-trips AL AÑO (ver costs.py). Un sistema que avise de
"oportunidades" bajo esa restricción sólo puede hacer dos cosas: mentir, o
empujarte a gastar el presupuesto anual de comisiones en una semana.

Así que este módulo notifica otra cosa: TRANSICIONES DE LA DECISIÓN. Nunca un
nivel ("el hurdle está en 10.84%"), siempre un cambio ("el hurdle se movió 52 pb
desde la última vez que te avisé"). Un nivel que no cambia no es noticia;
avisarlo diario entrena al usuario a ignorar la app, que es la peor falla
posible de un sistema de alertas.

Tres invariantes duras, cada una con test:

  1. Estado idéntico ⇒ CERO notificaciones. El silencio es el default correcto.
  2. Ningún trigger puede repetirse dentro de su cooldown, y el tope de 30 días
     es DURO para todas las prioridades. HIGH tiene su propio cupo dentro del
     tope (`max_high_per_30d`) y el resto queda reservado para MEDIUM/INFO: ni
     un aluvión de bloqueos puede tapar un cambio de hurdle, ni al revés. Lo que
     se cae por cupo de HIGH no se pierde en silencio: se resume en un aviso de
     intermitencia, porque el parpadeo ES la noticia.
  3. El presupuesto anual de avisos con ORDEN EJECUTABLE se DERIVA del
     presupuesto de comisiones. No se te puede pedir actuar más veces de las que
     puedes pagar actuar. La cuenta no es por nombre de trigger sino por
     contenido: cualquier aviso que te diga "mueve dinero" gasta presupuesto. Si
     la política genera más señal que eso, el sistema no te dice "opera más": te
     dice que la política está mal parametrizada.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import floor
from typing import Any, Callable, Literal

from .costs import CostBudget
from .decide import Decision

Priority = Literal["HIGH", "MEDIUM", "INFO"]

PRIORIDADES: tuple[str, ...] = ("HIGH", "MEDIUM", "INFO")

# Orden de evaluación. La entrega se ordena por PRIORIDAD primero y por este
# orden después: el cupo del tope rodante se consume así, de modo que si algo se
# cae, se caiga lo menos urgente.
TRIGGERS: tuple[str, ...] = (
    "ACTION_CHANGED",
    "BLOCKER_RAISED",
    "FEE_BUDGET_LOW",
    "BLOCKER_CLEARED",
    "REGIME_FLIPPED",
    "HURDLE_MOVED",
    "MATERIALITY_FLIPPED",
    "OVERTRADING_DETECTED",
    "FLAPPING_DETECTED",
)

# HIGH: puede costarte dinero o te prohíbe operar hoy.
# MEDIUM: cambia el encuadre de la decisión, no la decisión.
# INFO: mueve una referencia. Nunca pide nada. Es la clase que hace real la
#       reserva del tope rodante: si no existiera, "bajar de prioridad" sería
#       sinónimo de "no avisar".
PRIORIDAD_POR_TRIGGER: dict[str, str] = {
    "ACTION_CHANGED": "HIGH",
    "BLOCKER_RAISED": "HIGH",
    "FEE_BUDGET_LOW": "HIGH",
    "OVERTRADING_DETECTED": "HIGH",
    "BLOCKER_CLEARED": "MEDIUM",
    "REGIME_FLIPPED": "MEDIUM",
    "FLAPPING_DETECTED": "MEDIUM",
    "HURDLE_MOVED": "INFO",
    "MATERIALITY_FLIPPED": "INFO",
}

# Sólo estas acciones cuentan como "cambio de acción". Entrar o salir de un
# estado BLOQUEADO ya se avisa con BLOCKER_RAISED / BLOCKER_CLEARED; contarlo
# además como ACTION_CHANGED gastaría el presupuesto anual de avisos operables
# en un apagón de datos de Banxico, que no es una decisión de inversión.
ACCIONES_OPERABLES: frozenset[str] = frozenset(
    {"STAY_IN_CETES", "ALLOCATE_TO_CRYPTO", "REDUCE_CRYPTO", "HOLD_NO_ACTION"}
)

# Las únicas acciones cuyo plan operativo manda MOVER dinero, y por lo tanto
# pagar comisiones. STAY_IN_CETES y HOLD_NO_ACTION dicen "no operes": no gastan
# presupuesto. Esta distinción es la que se cobra contra el presupuesto anual,
# porque lo que cuesta comisiones es la orden, no el nombre del trigger.
ACCIONES_QUE_CUESTAN: frozenset[str] = frozenset({"ALLOCATE_TO_CRYPTO", "REDUCE_CRYPTO"})

ACCION_CORTA: dict[str, str] = {
    "STAY_IN_CETES": "CETES",
    "ALLOCATE_TO_CRYPTO": "Comprar cripto",
    "REDUCE_CRYPTO": "Reducir cripto",
    "HOLD_NO_ACTION": "Sin acción",
    "BLOCKED_FEE_BUDGET": "Bloqueo comisiones",
    "BLOCKED_STALE_DATA": "Bloqueo datos",
    "BLOCKED_BELOW_MIN_NOTIONAL": "Bloqueo mínimo",
}

# Tipos de registro en el historial append-only (snapshots/notifications.json).
# El historial no es sólo un log: es la ÚNICA memoria entre corridas. El cron
# arranca un proceso nuevo cada día; sin estos registros la histéresis y los
# cooldowns no existirían.
KIND_NOTIFICACION = "notificacion"
KIND_SUPRESION = "supresion"
KIND_ESTADO = "estado"

MAX_TITULO = 60

# Un bloqueo cuyo texto sólo cambia en un número ("7 días de antigüedad" →
# "8 días de antigüedad") es EL MISMO bloqueo. Sin esta normalización, un
# apagón de datos de una semana dispararía BLOCKER_RAISED todos los días.
_NUMEROS = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Notification:
    trigger: str
    priority: str
    title: str
    body: str
    razonamiento: list[str]
    estrategia: list[str]
    changed_from: dict[str, Any]
    changed_to: dict[str, Any]
    fired_at: str
    dedup_key: str

    # ¿Este aviso contiene una orden que cuesta comisiones ("mueve N pesos")?
    # Es el campo contra el que se cobra el presupuesto anual. Vive aquí y no se
    # infiere del trigger porque el trigger no sabe qué acabó diciendo el texto:
    # BLOCKER_CLEARED y MATERIALITY_FLIPPED también pueden pedir una operación.
    es_orden_ejecutable: bool = False

    def __post_init__(self) -> None:
        # Validación dura, no advertencia (regla 6 de CLAUDE.md). Un título de
        # 90 caracteres se trunca en la notificación del teléfono justo donde
        # está el número que importa; prefiero que truene en el test.
        if self.priority not in PRIORIDADES:
            raise ValueError(f"Prioridad inválida: {self.priority!r}")
        if self.trigger not in TRIGGERS:
            raise ValueError(f"Trigger desconocido: {self.trigger!r}")
        if len(self.title) > MAX_TITULO:
            raise ValueError(
                f"Título de {len(self.title)} caracteres (máximo {MAX_TITULO}): {self.title!r}"
            )
        if not self.estrategia:
            raise ValueError("Una notificación sin estrategia es ruido; no se emite.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_record(self) -> dict[str, Any]:
        return {"kind": KIND_NOTIFICACION, **asdict(self)}


def _cooldowns_por_defecto() -> dict[str, int]:
    """
    Días de silencio por trigger después de disparar.

    Estos números son JUICIOS, no datos, y por eso viven juntos y nombrados en
    vez de dispersos como constantes mágicas (regla 5 de CLAUDE.md). El criterio
    es la velocidad del proceso subyacente: la curva de CETES no se reprecia
    todos los días y el régimen de un activo no cambia en 48 horas, así que
    avisar de eso más seguido es ruido por construcción.
    """
    return {
        "ACTION_CHANGED": 3,
        # 3 días, no 1. Con cadencia diaria del cron, un cooldown de 1 día no
        # silencia NADA: la comparación es `días_transcurridos < cooldown` y dos
        # corridas consecutivas están exactamente a 1.0 días. Un bloqueo que
        # entra y sale disparaba 182 avisos al año con el valor anterior.
        "BLOCKER_RAISED": 3,
        "BLOCKER_CLEARED": 3,
        # El resumen de intermitencia es un diagnóstico de estado, no un evento:
        # una vez al mes basta para decir "esto lleva semanas parpadeando".
        "FLAPPING_DETECTED": 30,
        "REGIME_FLIPPED": 14,         # SMA200 no cambia de lado dos veces por quincena
        "HURDLE_MOVED": 21,           # Banxico decide tasa cada ~6 semanas
        "MATERIALITY_FLIPPED": 30,
        "FEE_BUDGET_LOW": 90,         # es un ESTADO, no un evento: basta una vez por trimestre
        "OVERTRADING_DETECTED": 90,
    }


@dataclass(frozen=True)
class NotifyPolicy:
    """
    Política de notificación. Todo lo subjetivo del módulo vive aquí.

    Mismo contrato que config.py: si un umbral no está aquí con su comentario,
    es un número inventado y por lo tanto un bug.
    """

    # Silencio por trigger tras cada disparo. Parcial: lo que no esté aquí cae
    # en `default_cooldown_days`.
    cooldown_days: dict[str, int] = field(default_factory=_cooldowns_por_defecto)
    default_cooldown_days: int = 7

    # Tope global rodante. Es DURO: ninguna prioridad lo esquiva. Que HIGH lo
    # esquivara convertía la excepción en el canal normal — un apagón
    # intermitente de Banxico entregaba 365 avisos al año contra un tope nominal
    # de 4. El tope real de un sistema que paga ~1.7 operaciones anuales tiene
    # que caber en un mes sin que el usuario aprenda a ignorarlo.
    max_per_30d: int = 5
    rolling_window_days: int = 30

    # Reparto del tope en dos cupos que lo SUMAN. Los tres números son JUICIOS,
    # no datos, y por eso viven juntos:
    #
    # `max_high_per_30d` = 3: lo que puede llevarse la prioridad alta. Tres
    # bloqueos duros en un mes ya describen una fuente de datos rota; el cuarto
    # no agrega información, agrega ruido, y por eso se resume.
    #
    # `medium_reserve_per_30d` = 2: lo que queda RESERVADO para MEDIUM/INFO. Es
    # un piso, no un sobrante. Sin él un aluvión de HIGH dejaba el presupuesto en
    # cero y el usuario nunca volvía a enterarse de que el hurdle se movió (265
    # avisos MEDIUM ahogados en un año simulado). Dos, no uno, porque con uno
    # solo los cooldowns propios de esa clase (BLOCKER_CLEARED 3d,
    # REGIME_FLIPPED 14d, HURDLE_MOVED 21d) nunca podrían llegar a mandar: el
    # cupo los taparía siempre y serían parámetros decorativos.
    #
    # Se cuentan POR SEPARADO: ninguna clase puede consumir el cupo de la otra,
    # ni HIGH tapa a INFO ni INFO tapa a HIGH. La suma sigue siendo el tope.
    max_high_per_30d: int = 3
    medium_reserve_per_30d: int = 2

    # Ventana para contar el parpadeo de un mismo trigger. 30 días es el mismo
    # horizonte del tope rodante a propósito: si algo consumió el cupo de HIGH,
    # el resumen habla exactamente de esa ventana.
    flap_window_days: int = 30

    # Histéresis de HURDLE_MOVED, en tasa anualizada (0.0050 = 50 pb).
    # Dispara a `enter` y sólo se RE-ARMA cuando el hurdle regresa a menos de
    # `rearm` de la referencia. Sin esto, un hurdle oscilando alrededor de los
    # 50 pb dispara cada vez que cruza la línea.
    hurdle_hysteresis_enter: float = 0.0050
    hurdle_hysteresis_rearm: float = 0.0025

    # Escape de la histéresis: un movimiento monótono nunca "regresa" a la
    # referencia y dejaría el trigger mudo para siempre. Si el hurdle se aleja
    # este múltiplo del umbral de entrada, se considera un movimiento NUEVO y
    # el trigger se re-arma. Sin este escape, una subida sostenida de tasas
    # (exactamente cuando más importa) sería silenciosa.
    hurdle_rearm_runaway_multiple: float = 2.0

    # Cuánto tiempo recuerda el motor los NIVELES de hurdle que ya te enseñó.
    # Un candidato sólo se emite si está a más de `hurdle_hysteresis_enter` de
    # TODOS ellos. Sin esta memoria, un hurdle que rebota entre dos niveles
    # fijos re-arma la histéresis en cada vuelta y avisa 18 veces al año de un
    # movimiento que termina en cero. 365 días porque el ciclo de Banxico es
    # anual: el mismo par de niveles dentro del mismo ejercicio es la misma
    # noticia, por más veces que se cruce.
    hurdle_niveles_memoria_dias: int = 365

    # Presupuesto anual de avisos con ORDEN EJECUTABLE.
    # None ⇒ SE DERIVA de cost_budget.max_round_trips_per_year. Es el default a
    # propósito: fijarlo a mano permitiría pedir más acciones de las que el
    # presupuesto de comisiones puede pagar, que es justo el error que este
    # módulo existe para impedir.
    max_action_changes_per_year: int | None = None
    action_window_days: int = 365

    # Cuánto tendría que subir el hurdle para invalidar una recomendación ya
    # emitida pero no ejecutada. 100 pb: un movimiento de esa magnitud entre el
    # aviso y la ejecución cambia la aritmética que produjo el aviso.
    invalidation_hurdle_bp: float = 0.0100

    def __post_init__(self) -> None:
        # Validación dura, no advertencia (regla 6). Una política mal repartida
        # deja a alguna clase con cupo cero, que es la falla que estos campos
        # existen para impedir; prefiero que truene al construirla.
        if self.max_high_per_30d + self.medium_reserve_per_30d > self.max_per_30d:
            raise ValueError(
                f"Reparto imposible: HIGH {self.max_high_per_30d} + reserva"
                f" {self.medium_reserve_per_30d} > tope {self.max_per_30d}."
            )
        if self.max_high_per_30d <= 0 or self.medium_reserve_per_30d <= 0:
            raise ValueError("Cada clase de prioridad necesita cupo propio mayor que cero.")

    def cooldown_for(self, trigger: str) -> int:
        return int(self.cooldown_days.get(trigger, self.default_cooldown_days))

    def cupo_alto(self) -> int:
        """Avisos HIGH permitidos por ventana rodante."""
        return min(self.max_high_per_30d, self.max_per_30d - self.medium_reserve_per_30d)

    def cupo_bajo(self) -> int:
        """
        Avisos MEDIUM/INFO permitidos por ventana rodante.

        Se cuenta APARTE del cupo de HIGH, no como sobrante: los dos cupos suman
        el tope global, así que ninguna clase puede consumir el de la otra y el
        total sigue siendo duro.
        """
        return self.max_per_30d - self.cupo_alto()

    def max_action_changes(self, cost_budget: CostBudget | dict[str, Any] | None) -> int:
        """
        Cuántos ACTION_CHANGED al año puede pagar esta cuenta.

        Derivado, no configurado: `max_round_trips_per_year` ya es el número de
        veces que el capital puede entrar y salir dentro del presupuesto anual
        de comisiones. Se trunca hacia abajo — 1.67 round-trips son 1, no 2 —
        porque redondear a favor de operar más es exactamente la falla que este
        repo existe para evitar.
        """
        if self.max_action_changes_per_year is not None:
            return int(self.max_action_changes_per_year)
        rt = _max_round_trips(cost_budget)
        if rt is None:
            # Sin presupuesto no hay derivación posible. 1 es el piso defendible:
            # 0 apagaría el sistema y cualquier número mayor sería inventado.
            return 1
        return max(1, int(floor(rt)))


# ---------------------------------------------------------------- utilidades


def _max_round_trips(cost_budget: CostBudget | dict[str, Any] | None) -> float | None:
    """
    Acepta el CostBudget del engine o el dict ya serializado de `Decision.costs`.
    El CLI sólo tiene el dict (viene del snapshot); los tests tienen el objeto.
    """
    if cost_budget is None:
        return None
    if isinstance(cost_budget, CostBudget):
        return cost_budget.max_round_trips_per_year
    valor = cost_budget.get("max_round_trips_per_year")
    return None if valor is None else float(valor)


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    # Un timestamp sin zona es ambiguo, no faltante: se normaliza a UTC, que es
    # lo que escribe decide.py. No se inventa ningún dato.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _dias(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 86_400.0


def _digest(partes: list[str]) -> str:
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:12]


def _blocker_key(s: str) -> str:
    return _NUMEROS.sub("#", s).strip().lower()


def _num(d: dict[str, Any] | None, *ruta: str) -> float | None:
    """
    Lee un número anidado. Devuelve None si falta: nunca un default.

    NaN e infinito cuentan como FALTANTE, no como valor. Un snapshot con nan en
    el hurdle es un dato roto, y el módulo ya sabe callarse ante un hueco; sin
    esta guarda lo publicaba como texto ("Hurdle nan% → 11.44%") en el teléfono.
    """
    cur: Any = d
    for k in ruta:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    return float(cur) if math.isfinite(float(cur)) else None


def _txt(d: dict[str, Any] | None, *ruta: str) -> str | None:
    cur: Any = d
    for k in ruta:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur if isinstance(cur, str) else None


def _mxn(x: float) -> str:
    return f"{x:,.0f} MXN"


def _regime_labels(d: Decision) -> dict[str, str]:
    """
    `sizing.regimes` no trae el símbolo: viene de asdict(RegimeState) y el orden
    es el de policy.universe.crypto_symbols. Se re-etiqueta aquí para que la
    notificación diga "BTC" y no "activo 0".
    """
    regimes = d.sizing.get("regimes") or []
    universo = d.policy.get("universe") if isinstance(d.policy, dict) else None
    simbolos = list((universo or {}).get("crypto_symbols") or [])
    out: dict[str, str] = {}
    for i, r in enumerate(regimes):
        if not isinstance(r, dict) or "label" not in r:
            continue
        sym = str(simbolos[i]) if i < len(simbolos) else f"activo_{i}"
        out[sym] = str(r["label"])
    return out


def _corto(simbolo: str) -> str:
    return simbolo.replace("USDT", "").replace("USD", "") or simbolo


def _historial(history: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    # Un registro sin "kind" es una notificación: es el formato que escribían
    # las versiones anteriores del archivo y el historial es append-only.
    return [r for r in history if r.get("kind", KIND_NOTIFICACION) == kind]


def _ultimo(
    history: list[dict[str, Any]], *, trigger: str | None = None, dedup_key: str | None = None
) -> datetime | None:
    ultimo: datetime | None = None
    for r in _historial(history, KIND_NOTIFICACION):
        if trigger is not None and r.get("trigger") != trigger:
            continue
        if dedup_key is not None and r.get("dedup_key") != dedup_key:
            continue
        fecha = r.get("fired_at")
        if not isinstance(fecha, str):
            continue
        dt = _parse_iso(fecha)
        if ultimo is None or dt > ultimo:
            ultimo = dt
    return ultimo


def _en_ventana(
    history: list[dict[str, Any]],
    now: datetime,
    dias: float,
    filtro: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """
    Notificaciones entregadas dentro de los últimos `dias`, extremos incluidos.

    Cerrada por los dos lados a propósito: si el conteo excluyera el aviso de
    hace exactamente 30.0 días, un cron diario podría meter un aviso extra justo
    en el borde y el tope de 30 días sería de 30 días "más uno".
    """
    out: list[dict[str, Any]] = []
    for r in _historial(history, KIND_NOTIFICACION):
        fecha = r.get("fired_at")
        if not isinstance(fecha, str):
            continue
        if not (0 <= _dias(now, _parse_iso(fecha)) <= dias):
            continue
        if filtro is not None and not filtro(r):
            continue
        out.append(r)
    return out


def _cuenta_en_ventana(
    history: list[dict[str, Any]], now: datetime, dias: int, trigger: str | None = None
) -> int:
    filtro = None if trigger is None else (lambda r: r.get("trigger") == trigger)
    return len(_en_ventana(history, now, dias, filtro))


def _prioridad_de(r: dict[str, Any]) -> str:
    """
    Prioridad de un registro del historial.

    Los registros viejos no la traen; se deriva del trigger, que sí. El historial
    es append-only (regla 3): no se puede reescribir para agregarles el campo.
    """
    p = r.get("priority")
    if isinstance(p, str) and p in PRIORIDADES:
        return p
    return PRIORIDAD_POR_TRIGGER.get(str(r.get("trigger")), "MEDIUM")


def _fue_orden_ejecutable(r: dict[str, Any]) -> bool:
    """
    ¿Ese registro llevaba una orden que costaba comisiones?

    Fallback para historial escrito antes de que existiera el campo: en aquellas
    versiones el único aviso con orden era ACTION_CHANGED.
    """
    v = r.get("es_orden_ejecutable")
    if isinstance(v, bool):
        return v
    return r.get("trigger") == "ACTION_CHANGED"


def _bloqueos_ya_avisados(
    history: list[dict[str, Any]], now: datetime, dias: float
) -> set[str]:
    """
    Claves normalizadas de bloqueos ya reportados dentro de la ventana.

    Comparar sólo contra `previous.blockers` trata como NUEVO a un bloqueo que
    se fue ayer y volvió hoy. Un apagón intermitente de Banxico es exactamente
    eso, y así producía un aviso HIGH cada 48 horas.
    """
    vistos: set[str] = set()
    for r in _en_ventana(history, now, dias, lambda x: x.get("trigger") == "BLOCKER_RAISED"):
        destino = r.get("changed_to")
        if not isinstance(destino, dict):
            continue
        for b in destino.get("nuevos") or []:
            vistos.add(_blocker_key(str(b)))
    return vistos


def _niveles_de_hurdle_avisados(
    history: list[dict[str, Any]], now: datetime, dias: float
) -> list[float]:
    """
    Niveles de hurdle que el usuario YA vio, dentro de la ventana de memoria.

    Se guardan los dos extremos de cada aviso ("Hurdle 10.84% → 11.44%") porque
    los dos se le enseñaron. Volver a cualquiera de ellos no es información
    nueva, por más veces que se cruce el umbral en el camino.
    """
    niveles: list[float] = []
    for r in _en_ventana(history, now, dias, lambda x: x.get("trigger") == "HURDLE_MOVED"):
        for campo in ("changed_from", "changed_to"):
            v = _num(r.get(campo), "hurdle_total_anualizado")
            if v is not None:
                niveles.append(v)
    return niveles


# ------------------------------------------------------- estado de histéresis


def _hay_estado_persistido(history: list[dict[str, Any]]) -> bool:
    """¿Ya existe una referencia de histéresis guardada en el historial?"""
    return any(
        r.get("kind") == KIND_ESTADO and r.get("maquina") == "HURDLE_MOVED" for r in history
    )


def _estado_histeresis(
    history: list[dict[str, Any]], previous: Decision
) -> tuple[float | None, bool]:
    """
    Recupera (referencia, armado) de la memoria persistida.

    Es estado EXPLÍCITO, no una heurística reconstruida: el re-arme ocurre en
    días en los que no se emite nada, así que no puede inferirse de la lista de
    notificaciones. Por eso `evaluate_with_audit` devuelve también registros de
    tipo `estado` y el CLI los guarda en el mismo archivo append-only.
    """
    for r in reversed(history):
        if r.get("kind") == KIND_ESTADO and r.get("maquina") == "HURDLE_MOVED":
            ref = r.get("ref")
            if isinstance(ref, (int, float)):
                return float(ref), bool(r.get("armed", True))

    # Fallback: sin registro de estado, la referencia es el último valor del que
    # sí se avisó, y se asume ARMADO. Asumir armado puede costar un aviso de
    # más; asumir desarmado costaría un aviso de menos, que es el error caro.
    for r in reversed(_historial(history, KIND_NOTIFICACION)):
        if r.get("trigger") == "HURDLE_MOVED":
            ref = _num(r.get("changed_to"), "hurdle_total_anualizado")
            if ref is not None:
                return ref, True

    # Nunca se ha avisado NI se ha guardado estado: se siembra con el hurdle de
    # ayer y `evaluate_with_audit` persiste ese valor de inmediato. Antes no se
    # persistía hasta el primer aviso, así que la referencia volvía a ser "ayer"
    # cada día y el trigger medía la variación DIARIA, no la acumulada desde el
    # último aviso: una subida de 2 pb diarios (+730 pb al año, un ciclo completo
    # de Banxico) no disparaba nunca.
    return _num(previous.hurdle, "hurdle_total_anualizado"), True


# ------------------------------------------------------ textos de estrategia


def _invalidaciones(current: Decision, policy: NotifyPolicy) -> list[str]:
    """Toda estrategia tiene que decir qué la invalida, con números."""
    out: list[str] = []
    h = _num(current.hurdle, "hurdle_total_anualizado")
    if h is not None:
        out.append(
            f"INVALIDACIÓN: si antes de ejecutar el hurdle anualizado sube por arriba de"
            f" {h + policy.invalidation_hurdle_bp:.2%} (hoy {h:.2%}), no lo hagas: el"
            " rendimiento exigido ya no lo paga el tamaño de la posición."
        )
    rt = _num(current.costs, "round_trips_remaining")
    if rt is not None:
        out.append(
            f"INVALIDACIÓN: si `round_trips_remaining` baja de 1.0 (hoy {rt:.1f}), no"
            " ejecutes: el presupuesto ya no paga la vuelta completa y quedarías atrapado"
            " en la posición."
        )
    if _txt(current.sizing, "materiality", "veredicto") == "INMATERIAL":
        impacto = _num(current.sizing, "materiality", "peso_sobre_capital_total")
        pct = f" (±{impacto * 0.50:.2%} del portafolio con cripto ±50%)" if impacto else ""
        out.append(
            f"INVALIDACIÓN: el veredicto de materialidad es INMATERIAL{pct}. No ejecutar"
            " es una respuesta correcta, no una omisión."
        )
    return out


def _plan_operativo(current: Decision) -> list[str]:
    """La parte concreta: cuántos pesos, de dónde, a dónde y cuánto cuesta."""
    sleeve = _num(current.sizing, "weight_mxn")
    rt_mxn = _num(current.costs, "cost_per_round_trip_mxn")
    rt_pct = _num(current.costs, "cost_per_round_trip_pct")
    tenor = _num(current.hurdle, "tenor_days")
    tenor_txt = f"CETES {tenor:.0f}d" if tenor is not None else "CETES"
    patas = ", ".join(
        f"{_corto(k)} {_mxn(v)}"
        for k, v in current.allocation_mxn.items()
        if k not in ("reserva_liquidez",) and not k.startswith("CETES") and v > 0
    )
    costo = ""
    if rt_mxn is not None and rt_pct is not None:
        costo = f" Costo estimado {_mxn(rt_mxn)} ({rt_pct:.2%} ida y vuelta sobre el sleeve)."

    accion = current.action
    if accion == "ALLOCATE_TO_CRYPTO" and sleeve is not None:
        return [
            f"Mover {_mxn(sleeve)} de {tenor_txt} a cripto: {patas or 'sleeve objetivo'}."
            f"{costo}",
            "Una orden por pata. Partirla en varias entradas duplica el costo fijo sin"
            " reducir riesgo a este tamaño.",
        ]
    if accion == "REDUCE_CRYPTO" and sleeve is not None:
        return [
            f"Vender hasta dejar el sleeve en {_mxn(sleeve)} y regresar el resto a"
            f" {tenor_txt}.{costo}",
        ]
    if accion == "STAY_IN_CETES":
        cetes = next((v for k, v in current.allocation_mxn.items() if k.startswith("CETES")), None)
        destino = f" Destino: {_mxn(cetes)} en {tenor_txt}." if cetes is not None else ""
        return [
            f"No operes. El dimensionamiento por riesgo no justifica posición cripto"
            f" hoy.{destino}",
        ]
    if accion == "HOLD_NO_ACTION":
        return [
            "No operes. La desviación contra el objetivo cae dentro de la banda de"
            " no-operación: rebalancear cuesta más de lo que corrige.",
        ]
    if accion.startswith("BLOCKED"):
        return ["No operes. Hay un bloqueo duro activo; ninguna orden es válida hoy."]
    return ["No operes hoy."]


# ------------------------------------------------------------ constructores


def _n(
    trigger: str,
    title: str,
    body: str,
    razonamiento: list[str],
    estrategia: list[str],
    changed_from: dict[str, Any],
    changed_to: dict[str, Any],
    fired_at: str,
    dedup_key: str,
    es_orden_ejecutable: bool = False,
) -> Notification:
    return Notification(
        trigger=trigger,
        priority=PRIORIDAD_POR_TRIGGER[trigger],
        title=title,
        body=body,
        razonamiento=razonamiento,
        estrategia=estrategia,
        changed_from=changed_from,
        changed_to=changed_to,
        fired_at=fired_at,
        dedup_key=dedup_key,
        es_orden_ejecutable=es_orden_ejecutable,
    )


def _plan_pide_operar(current: Decision) -> bool:
    """¿El plan operativo de hoy manda mover dinero? Es lo que cobra comisiones."""
    return current.action in ACCIONES_QUE_CUESTAN and _num(current.sizing, "weight_mxn") is not None


def _accion_cambiada(
    current: Decision, previous: Decision, policy: NotifyPolicy, cuando: str
) -> Notification:
    antes, ahora = previous.action, current.action
    razones = [
        f"La acción recomendada pasó de {antes} a {ahora}.",
        current.headline or "(sin titular)",
    ]
    h = _num(current.hurdle, "hurdle_total_anualizado")
    h_prev = _num(previous.hurdle, "hurdle_total_anualizado")
    if h is not None and h_prev is not None:
        razones.append(
            f"Hurdle anualizado: {h_prev:.2%} → {h:.2%} ({(h - h_prev) * 10_000:+.0f} pb)."
        )
    sleeve = _num(current.sizing, "weight_mxn")
    sleeve_prev = _num(previous.sizing, "weight_mxn")
    if sleeve is not None and sleeve_prev is not None:
        razones.append(f"Sleeve objetivo: {_mxn(sleeve_prev)} → {_mxn(sleeve)}.")
    binding = _txt(current.sizing, "binding_constraint")
    if binding:
        razones.append(f"Restricción que manda hoy: {binding}.")
    rt = _num(current.costs, "round_trips_remaining")
    if rt is not None:
        razones.append(f"Presupuesto de comisiones: quedan {rt:.1f} operaciones completas.")

    return _n(
        "ACTION_CHANGED",
        f"Acción: {ACCION_CORTA.get(antes, antes)} → {ACCION_CORTA.get(ahora, ahora)}",
        f"La recomendación cambió de {ACCION_CORTA.get(antes, antes)} a"
        f" {ACCION_CORTA.get(ahora, ahora)}. Es el único tipo de aviso que puede costarte"
        " comisiones, y tu presupuesto anual paga muy pocos.",
        razones,
        _plan_operativo(current) + _invalidaciones(current, policy),
        {"action": antes},
        {"action": ahora},
        cuando,
        f"ACTION_CHANGED:{antes}->{ahora}",
        es_orden_ejecutable=_plan_pide_operar(current),
    )


def _bloqueo_nuevo(
    current: Decision, previous: Decision, policy: NotifyPolicy, nuevos: list[str], cuando: str
) -> Notification:
    titulo = "Bloqueo activado" if len(nuevos) == 1 else f"Bloqueos activados ({len(nuevos)})"
    razones = [f"Bloqueo nuevo: {b}" for b in nuevos]
    razones.append(
        f"Acción antes del bloqueo: {previous.action}. Acción publicada hoy: {current.action}."
    )
    razones.append(
        "Regla 4 del repo: los datos rancios y los presupuestos agotados bloquean, no"
        " degradan. No se publica una recomendación derivada de datos incompletos."
    )
    return _n(
        "BLOCKER_RAISED",
        titulo,
        "El motor dejó de emitir recomendación operable: hay al menos un bloqueo duro"
        " activo. Un bloqueo no es una advertencia; es un no.",
        razones,
        [
            "No operes mientras el bloqueo esté activo. Ninguna orden derivada de este"
            " snapshot es válida.",
            "Deja el capital donde está: la posición actual no requiere acción para"
            " sostenerse, y mover dinero bajo bloqueo gasta comisiones sin información.",
            "INVALIDACIÓN: el bloqueo se levanta solo cuando la corrida diaria vuelva a"
            " publicar una acción operable. No lo anticipes ejecutando a mano.",
        ],
        {"blockers": list(previous.blockers)},
        {"blockers": list(current.blockers), "nuevos": nuevos},
        cuando,
        f"BLOCKER_RAISED:{_digest(sorted(_blocker_key(b) for b in nuevos))}",
    )


def _bloqueo_liberado(
    current: Decision, previous: Decision, policy: NotifyPolicy, idos: list[str], cuando: str
) -> Notification:
    titulo = "Bloqueo liberado" if len(idos) == 1 else f"Bloqueos liberados ({len(idos)})"
    razones = [f"Ya no aparece: {b}" for b in idos]
    razones.append(f"Acción publicada hoy: {current.action}.")
    if current.blockers:
        razones.append(f"Siguen activos {len(current.blockers)} bloqueos.")
    return _n(
        "BLOCKER_CLEARED",
        titulo,
        "Desapareció un bloqueo duro. Eso NO es una señal de compra: sólo significa que"
        " el motor volvió a poder calcular.",
        razones,
        # SIN plan operativo a propósito. Embeber aquí "Mover N MXN a cripto"
        # convertía cada parpadeo de un bloqueo en una orden de gasto: 23 al año
        # contra un presupuesto que paga 1.67. El plan sale por ACTION_CHANGED,
        # que sí se cobra contra el presupuesto anual, o no sale.
        [
            "Que se libere un bloqueo no crea una oportunidad. Si la acción del día no"
            " cambió, no hay nada que ejecutar.",
            "Si el motor decide que hay algo que mover, llegará un ACTION_CHANGED aparte;"
            " ése sí puede costarte comisiones y por eso está racionado.",
        ]
        + _invalidaciones(current, policy),
        {"blockers": list(previous.blockers)},
        {"blockers": list(current.blockers), "liberados": idos},
        cuando,
        f"BLOCKER_CLEARED:{_digest(sorted(_blocker_key(b) for b in idos))}",
    )


def _regimen_cambiado(
    current: Decision,
    previous: Decision,
    policy: NotifyPolicy,
    cambios: list[tuple[str, str, str]],
    cuando: str,
) -> Notification:
    if len(cambios) == 1:
        sym, antes, ahora = cambios[0]
        titulo = f"Régimen {_corto(sym)}: {antes} → {ahora}"
    else:
        titulo = f"Régimen cambió en {len(cambios)} activos"
    razones = [f"{sym}: régimen {antes} → {ahora}." for sym, antes, ahora in cambios]
    mult = _num(current.sizing, "regime_multiplier")
    mult_prev = _num(previous.sizing, "regime_multiplier")
    if mult is not None and mult_prev is not None:
        razones.append(
            f"Multiplicador de tamaño combinado (el mínimo del sleeve): {mult_prev:.2f} →"
            f" {mult:.2f}."
        )
    sleeve = _num(current.sizing, "weight_mxn")
    sleeve_prev = _num(previous.sizing, "weight_mxn")
    if sleeve is not None and sleeve_prev is not None:
        razones.append(f"Efecto en el sleeve objetivo: {_mxn(sleeve_prev)} → {_mxn(sleeve)}.")
    razones.append(
        "El régimen NO pronostica precio: sólo puede reducir tamaño, nunca amplificarlo."
    )
    return _n(
        "REGIME_FLIPPED",
        titulo,
        "Cambió la etiqueta de régimen de al menos un activo del sleeve. Eso mueve el"
        " tamaño permitido, no la dirección esperada.",
        razones,
        [
            f"El objetivo de sleeve de hoy es {_mxn(sleeve)}."
            if sleeve is not None
            else "Revisa el objetivo de sleeve del snapshot de hoy.",
            "No ejecutes por este aviso. Sólo ejecuta si la acción del día cambia:"
            " un cambio de régimen dentro de la banda de no-operación no paga comisiones.",
        ]
        + _invalidaciones(current, policy),
        {"regimes": {s: a for s, a, _ in cambios}},
        {"regimes": {s: b for s, _, b in cambios}},
        cuando,
        f"REGIME_FLIPPED:{_digest([f'{s}:{a}->{b}' for s, a, b in sorted(cambios)])}",
    )


def _hurdle_movido(
    current: Decision, policy: NotifyPolicy, ref: float, ahora: float, cuando: str
) -> Notification:
    pb = (ahora - ref) * 10_000
    razones = [
        f"El hurdle anualizado pasó de {ref:.2%} a {ahora:.2%} ({pb:+.0f} pb) desde el"
        " último aviso.",
        f"Umbral de aviso: {policy.hurdle_hysteresis_enter * 10_000:.0f} pb; re-arme a"
        f" {policy.hurdle_hysteresis_rearm * 10_000:.0f} pb. Movimientos menores no se"
        " avisan por diseño.",
    ]
    nominal = _num(current.hurdle, "cetes_nominal")
    neto = _num(current.hurdle, "cetes_neto_nominal")
    tenor = _num(current.hurdle, "tenor_days")
    prima = _num(current.hurdle, "prima_de_riesgo_exigida")
    if None not in (nominal, neto, tenor, prima):
        razones.append(
            f"Composición hoy: CETES {tenor:.0f}d {nominal:.2%} nominal → {neto:.2%} neto de"
            f" ISR sobre interés real, más prima de riesgo exigida {prima:.2%}."
        )
    materia = _txt(current.sizing, "materiality", "veredicto")
    if materia:
        razones.append(f"Veredicto de materialidad sin cambio: {materia}.")

    if pb > 0:
        que_hacer = (
            "El hurdle SUBIÓ: CETES se volvió más caro de vencer. No hay operación que"
            " ejecutar; el efecto es que la barra para cripto es más alta, no que debas"
            " vender."
        )
    else:
        que_hacer = (
            "El hurdle BAJÓ: CETES paga menos. Aun así el tamaño del sleeve lo fija el"
            " riesgo, no el hurdle. No aumentes posición por este aviso."
        )
    return _n(
        "HURDLE_MOVED",
        f"Hurdle {ref:.2%} → {ahora:.2%}",
        f"El costo de oportunidad libre de riesgo se movió {pb:+.0f} pb. Es un cambio de"
        " referencia, no una señal de operación.",
        razones,
        [
            que_hacer,
            "Cero órdenes por este trigger. Si el hurdle mueve la acción del día, llegará"
            " un ACTION_CHANGED aparte; ése sí puede costar comisiones.",
        ]
        + _invalidaciones(current, policy),
        {"hurdle_total_anualizado": ref},
        {"hurdle_total_anualizado": ahora, "delta_bp": pb},
        cuando,
        f"HURDLE_MOVED:{ref * 10_000:.0f}->{ahora * 10_000:.0f}",
    )


def _materialidad_cambiada(
    current: Decision, policy: NotifyPolicy, antes: str, ahora: str, cuando: str
) -> Notification:
    peso = _num(current.sizing, "materiality", "peso_sobre_capital_total")
    cetes = _num(current.sizing, "materiality", "cetes_anual_mxn")
    sleeve = _num(current.sizing, "weight_mxn")
    razones = [f"El veredicto de materialidad pasó de {antes} a {ahora}."]
    if peso is not None:
        razones.append(
            f"El sleeve pesa {peso:.2%} del capital total; con cripto ±50% el portafolio"
            f" se mueve {peso * 0.50:+.2%}."
        )
    if cetes is not None:
        razones.append(f"Contra eso, CETES paga {_mxn(cetes)} al año, neto y sin volatilidad.")

    if ahora == "INMATERIAL":
        plan = [
            f"Considera cerrar el sleeve de {_mxn(sleeve)} y ahorrarte el trabajo operativo"
            " y fiscal: a este peso, acertar no te cambia el resultado."
            if sleeve is not None
            else "Considera cerrar el sleeve: a este peso, acertar no cambia el resultado.",
            "Si decides cerrarlo, hazlo en UNA salida. Cerrar en partes gasta dos veces el"
            " presupuesto de comisiones para el mismo resultado.",
        ]
    else:
        plan = [
            f"El sleeve de {_mxn(sleeve)} ya mueve la aguja del portafolio."
            if sleeve is not None
            else "El sleeve ya mueve la aguja del portafolio.",
            "Eso NO es razón para aumentarlo. El tamaño lo fija el presupuesto de caída,"
            " no la sensación de relevancia.",
        ]
    return _n(
        "MATERIALITY_FLIPPED",
        f"Materialidad: {antes} → {ahora}",
        f"El sleeve cripto cambió de {antes} a {ahora} respecto del portafolio total.",
        razones,
        plan + _invalidaciones(current, policy),
        {"veredicto": antes},
        {"veredicto": ahora},
        cuando,
        f"MATERIALITY_FLIPPED:{antes}->{ahora}",
        # "Considera cerrar el sleeve de N MXN" es una orden de venta con todas
        # sus letras: cuesta lo mismo que cualquier otra y se cobra igual.
        es_orden_ejecutable=(ahora == "INMATERIAL" and sleeve is not None and sleeve > 0),
    )


def _presupuesto_bajo(
    current: Decision, policy: NotifyPolicy, antes: float, ahora: float, cuando: str
) -> Notification:
    gastado = _num(current.costs, "fees_spent_ytd_mxn")
    anual = _num(current.costs, "annual_budget_mxn")
    rt_mxn = _num(current.costs, "cost_per_round_trip_mxn")
    razones = [
        f"Operaciones completas restantes: {antes:.2f} → {ahora:.2f}. Cruzó por debajo de 1.0.",
        "Menos de una vuelta completa significa que puedes entrar pero no salir dentro del"
        " presupuesto. Entrar así es quedarse atrapado por comisiones.",
    ]
    if gastado is not None and anual is not None:
        razones.append(
            f"Comisiones del ejercicio: {_mxn(gastado)} de {_mxn(anual)} presupuestados."
        )
    if rt_mxn is not None:
        razones.append(f"Cada vuelta completa cuesta {_mxn(rt_mxn)} sobre el sleeve actual.")
    return _n(
        "FEE_BUDGET_LOW",
        "Comisiones: queda menos de una vuelta completa",
        "El presupuesto anual de comisiones ya no paga un round-trip. A partir de aquí el"
        " motor bloquea en duro cualquier cambio de posición.",
        razones,
        [
            "No abras ni cierres posición por señal. Sostener lo que ya tienes cuesta cero.",
            "Si de verdad necesitas salir, es una decisión de liquidez, no del motor, y"
            f" cuesta {_mxn(rt_mxn)} en comisiones."
            if rt_mxn is not None
            else "Si de verdad necesitas salir, es una decisión de liquidez, no del motor.",
            "El presupuesto se repone en el corte anual, no cuando el mercado se ponga"
            " interesante.",
            "INVALIDACIÓN: sólo actualizar `fees_spent_ytd_mxn` a un valor menor reabre el"
            " presupuesto; hacerlo sin haber pagado menos comisiones es mentirle al motor.",
        ],
        {"round_trips_remaining": antes},
        {"round_trips_remaining": ahora},
        cuando,
        "FEE_BUDGET_LOW:<1.0",
    )


def _sobreoperacion(
    current: Decision,
    policy: NotifyPolicy,
    cost_budget: CostBudget | dict[str, Any] | None,
    emitidos: int,
    permitidos: int,
    suprimida: Notification,
    cuando: str,
) -> Notification:
    rt = _max_round_trips(cost_budget)
    rt_txt = f"{rt:.2f}" if rt is not None else "n/d"
    razones = [
        f"En los últimos {policy.action_window_days} días la política generó"
        f" {emitidos + 1} avisos con orden ejecutable; el presupuesto de comisiones paga"
        f" {permitidos}.",
        f"Presupuesto: {rt_txt} round-trips al año. El aviso número {emitidos + 1}"
        f" ({suprimida.title}, {suprimida.trigger}) se suprimió.",
        "Esto NO significa que debas operar más. Significa lo contrario: la política está"
        " produciendo más señal de la que tu cuenta puede pagar, así que los parámetros"
        " están mal, no el mercado.",
        "Ejecutar cada señal a este ritmo transfiere el rendimiento esperado al exchange"
        " en comisiones.",
    ]
    return _n(
        "OVERTRADING_DETECTED",
        "Sobreoperación: más señales que presupuesto",
        f"El motor quiso mandarte la orden número {emitidos + 1} en"
        f" {policy.action_window_days} días, y sólo puedes pagar {permitidos}. Se suprimió"
        " el aviso.",
        razones,
        [
            "No operes. La acción correcta ante esta meta-notificación es revisar la"
            " política, no el portafolio.",
            "Revisa en este orden: (1) sube `required_risk_premium`, (2) sube"
            " `REBALANCE_BAND_RELATIVE` en decide.py para ensanchar la banda de"
            " no-operación, (3) baja `max_crypto_weight` para que el sleeve rote menos.",
            "Cada cambio de esos exige justificarse con el log walk-forward de"
            " `snapshots/`, no con la corrida de hoy.",
            f"INVALIDACIÓN: este diagnóstico deja de aplicar sólo si"
            f" `max_round_trips_per_year` sube por encima de {emitidos + 1} por un cambio"
            " REAL de comisiones del venue o de tamaño de cuenta; subirlo a mano para"
            " callar el aviso es exactamente el error que describe.",
        ],
        {"action_changes_365d": emitidos, "presupuesto": permitidos},
        {"action_changes_365d": emitidos + 1, "suprimida": suprimida.dedup_key},
        cuando,
        f"OVERTRADING_DETECTED:{emitidos + 1}/{permitidos}",
    )


def _intermitencia(
    policy: NotifyPolicy,
    trigger: str,
    repeticiones: int,
    suprimida: Notification,
    cuando: str,
) -> Notification:
    """
    Resumen de parpadeo: lo que se cae por cupo de HIGH no desaparece.

    Descartar en silencio un bloqueo que entra y sale seis veces en dos semanas
    le esconde al usuario el único dato que importa de esa situación: que la
    fuente está inestable. El parpadeo ES la noticia, y cabe en un solo aviso al
    mes en vez de en seis avisos de alta prioridad.
    """
    razones = [
        f"{trigger} se disparó {repeticiones} veces en los últimos"
        f" {policy.flap_window_days} días. Último: {suprimida.title}.",
        f"El cupo de prioridad alta es de {policy.cupo_alto()} avisos por"
        f" {policy.rolling_window_days} días; ya se consumió, así que el resto se resume"
        " aquí en vez de entregarse uno por uno.",
        "Que algo entre y salga a diario no es una secuencia de noticias: es UNA noticia,"
        " y es sobre la fuente de datos, no sobre tu portafolio.",
    ]
    return _n(
        "FLAPPING_DETECTED",
        f"Intermitencia: {repeticiones} avisos en {policy.flap_window_days}d",
        f"El motor intentó avisarte {repeticiones} veces del mismo tipo de cambio"
        f" ({trigger}) en {policy.flap_window_days} días. Se agrupan en este resumen.",
        razones,
        [
            "No operes. Un estado que parpadea no es una decisión de inversión; ninguna"
            " orden derivada de un dato inestable es válida.",
            "Si el parpadeo viene de datos rancios, la acción es revisar la fuente"
            " (Banxico/Binance), no el portafolio.",
            f"INVALIDACIÓN: este resumen deja de aplicar cuando {trigger} pase"
            f" {policy.flap_window_days} días seguidos sin dispararse.",
        ],
        {"trigger": trigger, "ventana_dias": policy.flap_window_days},
        {"repeticiones": repeticiones, "ultima_suprimida": suprimida.dedup_key},
        cuando,
        f"FLAPPING_DETECTED:{trigger}",
    )


# ------------------------------------------------------------------ motor


def _orden_de_entrega(n: Notification) -> tuple[int, int]:
    """
    Prioridad primero, orden de evaluación después.

    Importa porque el cupo se consume en este orden: si algo se cae, que se caiga
    lo menos urgente. Ordenar sólo por `TRIGGERS` dejaba OVERTRADING_DETECTED
    (HIGH) al final, detrás de dos INFO.
    """
    return (PRIORIDADES.index(n.priority), TRIGGERS.index(n.trigger))


def _candidatos(
    current: Decision,
    previous: Decision,
    history: list[dict[str, Any]],
    policy: NotifyPolicy,
    cuando: str,
) -> tuple[list[Notification], tuple[float | None, bool], tuple[float | None, bool]]:
    """
    Construye los candidatos y devuelve el estado de histéresis (antes, después).

    Ningún trigger es un NIVEL. Todos son transiciones: sin `previous` no hay
    candidato posible.
    """
    fuera: list[Notification] = []
    now = _parse_iso(cuando)

    # --- bloqueos: se comparan por clave normalizada, no por string crudo ---
    # Y no sólo contra AYER: también contra los que ya se avisaron dentro del
    # cooldown, leídos del historial. Un bloqueo que se va y vuelve no es nuevo.
    antes_bloq = {_blocker_key(b): b for b in previous.blockers}
    hoy_bloq = {_blocker_key(b): b for b in current.blockers}
    ya_avisados = _bloqueos_ya_avisados(
        history, now, policy.cooldown_for("BLOCKER_RAISED")
    )
    nuevos = [hoy_bloq[k] for k in hoy_bloq.keys() - antes_bloq.keys() - ya_avisados]
    idos = [antes_bloq[k] for k in antes_bloq.keys() - hoy_bloq.keys()]

    ref_ini, armado_ini = _estado_histeresis(history, previous)
    estado_final = (ref_ini, armado_ini)

    # Datos rancios: el snapshot viene con hurdle, sizing y costs VACÍOS (ver
    # decide.py). Cualquier otro trigger se calcularía sobre huecos, y comparar
    # contra huecos produce avisos falsos. Regla 4: bloquean, no degradan.
    if current.action == "BLOCKED_STALE_DATA":
        if nuevos:
            fuera.append(_bloqueo_nuevo(current, previous, policy, sorted(nuevos), cuando))
        return fuera, (ref_ini, armado_ini), estado_final

    if (
        current.action != previous.action
        and current.action in ACCIONES_OPERABLES
        and previous.action in ACCIONES_OPERABLES
    ):
        fuera.append(_accion_cambiada(current, previous, policy, cuando))

    if nuevos:
        fuera.append(_bloqueo_nuevo(current, previous, policy, sorted(nuevos), cuando))

    rt_antes = _num(previous.costs, "round_trips_remaining")
    rt_hoy = _num(current.costs, "round_trips_remaining")
    if rt_antes is not None and rt_hoy is not None and rt_antes >= 1.0 > rt_hoy:
        fuera.append(_presupuesto_bajo(current, policy, rt_antes, rt_hoy, cuando))

    if idos:
        fuera.append(_bloqueo_liberado(current, previous, policy, sorted(idos), cuando))

    reg_antes, reg_hoy = _regime_labels(previous), _regime_labels(current)
    cambios = sorted(
        (sym, reg_antes[sym], reg_hoy[sym])
        for sym in reg_antes.keys() & reg_hoy.keys()
        if reg_antes[sym] != reg_hoy[sym]
    )
    if cambios:
        fuera.append(_regimen_cambiado(current, previous, policy, cambios, cuando))

    # --- histéresis explícita del hurdle ---
    h_hoy = _num(current.hurdle, "hurdle_total_anualizado")
    if h_hoy is not None and ref_ini is not None:
        armado = armado_ini
        distancia = abs(h_hoy - ref_ini)
        if not armado and (
            distancia <= policy.hurdle_hysteresis_rearm
            or distancia >= policy.hurdle_hysteresis_enter * policy.hurdle_rearm_runaway_multiple
        ):
            armado = True
        estado_final = (ref_ini, armado)
        # Además de la distancia a la referencia, el destino tiene que ser NUEVO
        # frente a todos los niveles que el usuario ya vio. Sin esto, un rebote
        # entre dos niveles fijos re-arma la histéresis en cada vuelta y avisa
        # una y otra vez de un movimiento cuyo neto es cero.
        niveles = _niveles_de_hurdle_avisados(history, now, policy.hurdle_niveles_memoria_dias)
        es_nivel_nuevo = all(
            abs(h_hoy - nivel) >= policy.hurdle_hysteresis_enter for nivel in niveles
        )
        if armado and distancia >= policy.hurdle_hysteresis_enter and es_nivel_nuevo:
            fuera.append(_hurdle_movido(current, policy, ref_ini, h_hoy, cuando))

    mat_antes = _txt(previous.sizing, "materiality", "veredicto")
    mat_hoy = _txt(current.sizing, "materiality", "veredicto")
    if mat_antes in ("MATERIAL", "INMATERIAL") and mat_hoy in ("MATERIAL", "INMATERIAL"):
        if mat_antes != mat_hoy:
            fuera.append(_materialidad_cambiada(current, policy, mat_antes, mat_hoy, cuando))

    fuera.sort(key=_orden_de_entrega)
    return fuera, (ref_ini, armado_ini), estado_final


def evaluate_with_audit(
    current: Decision,
    previous: Decision | None,
    history: list[dict[str, Any]],
    policy: NotifyPolicy,
    cost_budget: CostBudget | dict[str, Any] | None,
) -> tuple[list[Notification], list[dict[str, Any]]]:
    """
    Igual que `evaluate`, pero devuelve además los registros de auditoría:
    cada supresión con su motivo y, cuando cambia, el estado de la histéresis.

    Existe porque "el descarte se registra" no puede cumplirse desde una función
    que sólo devuelve notificaciones: si TODO se descarta, la lista sale vacía y
    el descarte se pierde. El CLI persiste ambas cosas en el mismo archivo
    append-only, que es también la memoria de la histéresis entre corridas.
    """
    auditoria: list[dict[str, Any]] = []
    cuando = current.generated_at
    now = _parse_iso(cuando)

    # Primera corrida: no hay contra qué comparar. El silencio es correcto, y
    # además evita que el primer día del sistema gaste el presupuesto anual de
    # avisos de acción sólo por existir.
    if previous is None:
        return [], auditoria

    candidatos, estado_ini, estado_fin = _candidatos(current, previous, history, policy, cuando)

    def descarta(n: Notification, motivo: str, detalle: str) -> None:
        auditoria.append(
            {
                "kind": KIND_SUPRESION,
                "trigger": n.trigger,
                "priority": n.priority,
                "title": n.title,
                "dedup_key": n.dedup_key,
                "motivo": motivo,
                "detalle": detalle,
                "at": cuando,
            }
        )

    # ---------- 1. cooldown y dedup ----------
    # Va primero: algo silenciado por cooldown no debe consumir el presupuesto
    # anual de acciones ni el tope rodante.
    vivos: list[Notification] = []
    for n in candidatos:
        cd = policy.cooldown_for(n.trigger)
        ultimo_trigger = _ultimo(history, trigger=n.trigger)
        if ultimo_trigger is not None and _dias(now, ultimo_trigger) < cd:
            descarta(
                n,
                "cooldown",
                f"{n.trigger} disparó hace {_dias(now, ultimo_trigger):.1f} días"
                f" (cooldown {cd}).",
            )
            continue
        ultimo_dedup = _ultimo(history, dedup_key=n.dedup_key)
        if ultimo_dedup is not None and _dias(now, ultimo_dedup) < cd:
            descarta(
                n,
                "dedup",
                f"dedup_key {n.dedup_key} ya se emitió hace"
                f" {_dias(now, ultimo_dedup):.1f} días (cooldown {cd}).",
            )
            continue
        vivos.append(n)

    # ---------- 2. presupuesto anual de ÓRDENES EJECUTABLES ----------
    # Se cobra por CONTENIDO, no por nombre de trigger: cualquier aviso que te
    # mande mover dinero gasta presupuesto de comisiones, se llame ACTION_CHANGED
    # o MATERIALITY_FLIPPED. Contarlo por trigger dejaba pasar 23 órdenes al año
    # contra un presupuesto que paga 1.67.
    permitidos = policy.max_action_changes(cost_budget)
    emitidos = len(
        _en_ventana(history, now, policy.action_window_days, _fue_orden_ejecutable)
    )
    ajustados: list[Notification] = []
    for n in vivos:
        if not n.es_orden_ejecutable:
            ajustados.append(n)
            continue
        if emitidos + 1 <= permitidos:
            ajustados.append(n)
            # El contador sube DENTRO del bucle: dos órdenes el mismo día son dos
            # órdenes, y sin esto las dos pasaban contra un presupuesto de una.
            emitidos += 1
            continue
        descarta(
            n,
            "presupuesto_anual_de_acciones",
            f"{emitidos + 1} órdenes ejecutables en {policy.action_window_days} días contra"
            f" {permitidos} pagables por el presupuesto de comisiones.",
        )
        meta = _sobreoperacion(current, policy, cost_budget, emitidos, permitidos, n, cuando)
        cd = policy.cooldown_for(meta.trigger)
        ultimo_meta = _ultimo(history, trigger=meta.trigger)
        if ultimo_meta is not None and _dias(now, ultimo_meta) < cd:
            descarta(meta, "cooldown", f"OVERTRADING_DETECTED ya avisado (cooldown {cd}).")
        else:
            ajustados.append(meta)

    ajustados.sort(key=_orden_de_entrega)

    # ---------- 3. tope rodante de 30 días, con cupo por clase ----------
    # Dos cupos separados que suman el tope global. Separarlos es lo que impide
    # las dos fallas simétricas: que un aluvión de HIGH deje sin espacio a los
    # MEDIUM/INFO, y que un aluvión de MEDIUM/INFO tape un bloqueo duro. Ninguno
    # de los dos contadores baja de cero.
    W = policy.rolling_window_days
    ya_altas = len(_en_ventana(history, now, W, lambda r: _prioridad_de(r) == "HIGH"))
    ya_bajas = len(_en_ventana(history, now, W, lambda r: _prioridad_de(r) != "HIGH"))
    restantes_altas = max(policy.cupo_alto() - ya_altas, 0)
    restantes_bajas = max(policy.cupo_bajo() - ya_bajas, 0)

    emitidas: list[Notification] = []
    resumidos: dict[str, Notification] = {}
    for n in ajustados:
        alta = n.priority == "HIGH"
        if alta and restantes_altas > 0:
            emitidas.append(n)
            restantes_altas -= 1
            continue
        if not alta and restantes_bajas > 0:
            emitidas.append(n)
            restantes_bajas -= 1
            continue
        cupo, usados = (
            (policy.cupo_alto(), ya_altas) if alta else (policy.cupo_bajo(), ya_bajas)
        )
        descarta(
            n,
            "tope_30d",
            f"{usados} avisos de prioridad {'alta' if alta else 'baja'} en {W} días"
            f" (cupo {cupo} de un tope global de {policy.max_per_30d}).",
        )
        if alta:
            # Un HIGH que se cae no se pierde: se acumula para el resumen de
            # intermitencia. Uno por trigger; el último gana como ejemplo.
            resumidos[n.trigger] = n

    # ---------- 3b. resumen de intermitencia ----------
    for trigger, ejemplo in resumidos.items():
        repeticiones = _cuenta_en_ventana(history, now, policy.flap_window_days, trigger) + 1
        resumen = _intermitencia(policy, trigger, repeticiones, ejemplo, cuando)
        cd = policy.cooldown_for(resumen.trigger)
        ultimo = _ultimo(history, dedup_key=resumen.dedup_key)
        if ultimo is not None and _dias(now, ultimo) < cd:
            descarta(
                resumen,
                "cooldown",
                f"resumen de intermitencia de {trigger} ya avisado hace"
                f" {_dias(now, ultimo):.1f} días (cooldown {cd}).",
            )
        elif restantes_bajas > 0:
            emitidas.append(resumen)
            restantes_bajas -= 1
        else:
            descarta(
                resumen,
                "tope_30d",
                f"{ya_bajas} avisos de prioridad baja en {W} días"
                f" (cupo {policy.cupo_bajo()}).",
            )
    emitidas.sort(key=_orden_de_entrega)

    # ---------- 4. estado de histéresis ----------
    ref_fin, armado_fin = estado_fin
    if any(n.trigger == "HURDLE_MOVED" for n in emitidas):
        # La referencia se mueve SÓLO si el aviso salió de verdad. Si se suprimió,
        # el usuario nunca vio el número nuevo y su referencia sigue siendo la vieja.
        nuevo = _num(current.hurdle, "hurdle_total_anualizado")
        ref_fin, armado_fin = nuevo, False
    # La referencia se persiste también la PRIMERA vez, aunque no haya cambiado
    # nada: es lo que la ancla. Guardarla sólo al avisar dejaba la referencia
    # reseteándose al valor de ayer en cada corrida, y con eso el trigger medía
    # el salto diario en vez del acumulado — una deriva lenta era invisible.
    cambio = (ref_fin, armado_fin) != estado_ini
    if ref_fin is not None and (cambio or not _hay_estado_persistido(history)):
        auditoria.append(
            {
                "kind": KIND_ESTADO,
                "maquina": "HURDLE_MOVED",
                "ref": ref_fin,
                "armed": armado_fin,
                "at": cuando,
            }
        )

    return emitidas, auditoria


def evaluate(
    current: Decision,
    previous: Decision | None,
    history: list[dict[str, Any]],
    policy: NotifyPolicy,
    cost_budget: CostBudget | dict[str, Any] | None,
) -> list[Notification]:
    """
    Devuelve las notificaciones que SÍ deben entregarse hoy.

    La lista vacía es el resultado esperado en un día normal. Si este motor
    habla todos los días, está roto — igual que el engine está roto si nunca
    recomienda STAY_IN_CETES.
    """
    return evaluate_with_audit(current, previous, history, policy, cost_budget)[0]
