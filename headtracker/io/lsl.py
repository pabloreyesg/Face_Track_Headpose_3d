from __future__ import annotations

from collections import deque
from dataclasses import asdict
import threading
import time
from typing import Optional

from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams, resolve_byprop, local_clock

from ..core.i18n import t
from ..core.models import MarkerEvent, LSLEvent, RuntimeStats


class MarkerBuffer:
    def __init__(self, maxlen=10000):
        self._events = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, event: MarkerEvent):
        with self._lock:
            self._events.append(event)

    def between(self, start_ts: float | None, end_ts: float) -> list[MarkerEvent]:
        if start_ts is None:
            start_ts = float("-inf")
        with self._lock:
            return [e for e in self._events if start_ts < e.timestamp <= end_ts]


class LSLIntegrityState:
    """Estado compartido del stream de markers, independiente de la frecuencia de triggers."""

    def __init__(self, enabled: bool, stream_info: Optional[dict] = None):
        self._lock = threading.Lock()
        self.enabled = enabled
        self.stream_info = stream_info or {}
        self.state = "CONNECTED" if enabled else "DISABLED"
        self.connected_at_start = enabled
        self.disconnect_count = 0
        self.reconnect_count = 0
        self.total_unavailable_seconds = 0.0
        self.current_unavailable_since: float | None = None
        self.last_transition_timestamp = float(local_clock())
        self.last_error: str | None = None
        self.recovery_limited = enabled and not bool(self.stream_info.get("source_id"))

    def transition(self, new_state: str, *, detail: str | None = None, timestamp: float | None = None):
        ts = float(local_clock() if timestamp is None else timestamp)
        with self._lock:
            old_state = self.state
            if new_state == old_state:
                if detail:
                    self.last_error = detail
                return None

            if new_state == "LOST":
                self.disconnect_count += 1
                if self.current_unavailable_since is None:
                    self.current_unavailable_since = ts
            elif new_state == "RECONNECTED":
                self.reconnect_count += 1
                if self.current_unavailable_since is not None:
                    self.total_unavailable_seconds += max(0.0, ts - self.current_unavailable_since)
                    self.current_unavailable_since = None
            elif new_state == "DISABLED":
                pass

            self.state = new_state
            self.last_transition_timestamp = ts
            if detail:
                self.last_error = detail
            return old_state, new_state, ts

    def snapshot(self) -> dict:
        now = float(local_clock())
        with self._lock:
            total = self.total_unavailable_seconds
            if self.current_unavailable_since is not None:
                total += max(0.0, now - self.current_unavailable_since)
            return {
                "state": self.state,
                "connected_at_start": self.connected_at_start,
                "disconnect_count": self.disconnect_count,
                "reconnect_count": self.reconnect_count,
                "total_unavailable_seconds": total,
                "currently_unavailable_since": self.current_unavailable_since,
                "last_transition_timestamp": self.last_transition_timestamp,
                "last_error": self.last_error,
                "source_id": self.stream_info.get("source_id") or None,
                "recovery_limited": self.recovery_limited,
                "lsl_available": self.state in ("CONNECTED", "RECONNECTED"),
            }

    def is_available(self) -> bool:
        return bool(self.snapshot()["lsl_available"])


class LSLWatchdog(threading.Thread):
    """Comprueba que la fuente seleccionada siga siendo descubrible por source_id.

    Nunca usa el tiempo desde el último marker como criterio: los streams event-driven
    pueden permanecer minutos legítimamente sin producir muestras.
    """

    def __init__(self, stream_info: dict, integrity: LSLIntegrityState, event_logger,
                 stop_event: threading.Event, check_interval_s: float = 3.0,
                 resolve_timeout_s: float = 0.75, lost_after_misses: int = 2):
        super().__init__(name="LSLWatchdog", daemon=True)
        self.stream_info = stream_info
        self.integrity = integrity
        self.event_logger = event_logger
        self.stop_event = stop_event
        self.check_interval_s = max(0.5, float(check_interval_s))
        self.resolve_timeout_s = max(0.05, float(resolve_timeout_s))
        self.lost_after_misses = max(1, int(lost_after_misses))
        self._misses = 0
        self._had_loss = False

    def _log(self, event: str, detail: str = ""):
        if self.event_logger is not None:
            self.event_logger.submit_lsl_event(LSLEvent(
                timestamp=float(local_clock()),
                event=event,
                source_id=self.stream_info.get("source_id", ""),
                stream_name=self.stream_info.get("name", ""),
                detail=detail,
            ))

    def run(self):
        source_id = (self.stream_info.get("source_id") or "").strip()
        if not source_id:
            self._log("RECOVERY_LIMITED", "Selected stream has no stable source_id; watchdog cannot verify identity reliably.")
            return

        self._log("CONNECTED", "Initial marker stream selected; watchdog started.")

        while not self.stop_event.wait(self.check_interval_s):
            try:
                found = resolve_byprop("source_id", source_id, minimum=1, timeout=self.resolve_timeout_s)
                visible = bool(found)
            except Exception as exc:
                visible = False
                detail = f"resolver error: {exc}"
            else:
                detail = "source_id visible" if visible else "source_id not visible"

            if visible:
                self._misses = 0
                state = self.integrity.snapshot()["state"]
                if state in ("LOST", "RECOVERING"):
                    transition = self.integrity.transition("RECONNECTED", detail=detail)
                    if transition:
                        self._log("RECONNECTED", detail)
                        print("\n" + t("lsl_reconnected"))
                    # Después de registrar RECONNECTED, el estado operativo vuelve a CONNECTED.
                    self.integrity.transition("CONNECTED", detail="stable after reconnection")
                continue

            self._misses += 1
            if self._misses < self.lost_after_misses:
                continue

            state = self.integrity.snapshot()["state"]
            if state not in ("LOST", "RECOVERING"):
                transition = self.integrity.transition("LOST", detail=detail)
                if transition:
                    self._log("LOST", f"source_id absent in {self._misses} consecutive checks")
                    print("\n" + t("lsl_lost"))
                self.integrity.transition("RECOVERING", detail="waiting for same source_id to reappear")
                self._log("RECOVERING", "waiting for same source_id")
            self._had_loss = True


class MarkerReceiver(threading.Thread):
    def __init__(self, inlet: StreamInlet, correction: float, buffer: MarkerBuffer,
                 marker_logger, stop_event: threading.Event, stats: RuntimeStats,
                 integrity: LSLIntegrityState | None = None):
        super().__init__(name="MarkerReceiver", daemon=True)
        self.inlet = inlet
        self.correction = correction
        self.buffer = buffer
        self.marker_logger = marker_logger
        self.stop_event = stop_event
        self.stats = stats
        self.integrity = integrity
        self.marker_id = 0
        self._last_error_print = 0.0

    def run(self):
        while not self.stop_event.is_set():
            try:
                sample, raw_ts = self.inlet.pull_sample(timeout=0.1)
                if not sample:
                    continue
                self.marker_id += 1
                event = MarkerEvent(
                    marker_id=self.marker_id,
                    value=str(sample[0]) if sample else "",
                    timestamp=float(raw_ts + self.correction),
                    raw_timestamp=float(raw_ts),
                )
                self.buffer.append(event)
                self.stats.marker_count += 1
                if self.marker_logger is not None:
                    self.marker_logger.submit_marker(event)
            except Exception as exc:
                # Una excepción es evidencia adicional de problema, pero no usamos silencio
                # de markers como señal de desconexión.
                if self.integrity is not None:
                    self.integrity.last_error = str(exc)
                now = time.monotonic()
                if now - self._last_error_print > 2.0:
                    print(t("marker_error", error=exc))
                    self._last_error_print = now
                time.sleep(0.05)


def create_outlet(cfg):
    info = StreamInfo(cfg.outlet_name, cfg.outlet_type, cfg.outlet_channels,
                      cfg.outlet_srate, "float32", cfg.outlet_source_id)
    return StreamOutlet(info)


def _search_streams_with_countdown(max_wait_seconds=40):
    """Busca streams LSL mostrando una cuenta regresiva visible."""
    timeout = max(1, int(round(max_wait_seconds)))
    deadline = time.monotonic() + timeout

    print(t("lsl_search", timeout=timeout))
    while True:
        remaining = max(0, int(deadline - time.monotonic() + 0.999))
        print("\r" + t("lsl_countdown", remaining=remaining), end="", flush=True)
        if remaining <= 0:
            print()
            return []

        wait_time = min(0.5, max(0.05, deadline - time.monotonic()))
        try:
            streams = resolve_streams(wait_time=wait_time)
        except TypeError:
            streams = resolve_streams()

        if streams:
            print("\r" + t("lsl_found", n=len(streams)) + (" " * 24))
            return streams

        time.sleep(0.1)


def _warn_no_lsl():
    print()
    print("⚠️" * 18)
    print(t("no_lsl_title"))
    print(t("no_lsl_1"))
    print(t("no_lsl_2"))
    print(t("no_lsl_3"))
    print("⚠️" * 18)
    print()


def stream_info_to_dict(info: StreamInfo) -> dict:
    return {
        "name": info.name(),
        "type": info.type(),
        "channel_count": info.channel_count(),
        "nominal_srate": info.nominal_srate(),
        "source_id": info.source_id(),
        "hostname": info.hostname(),
        "uid": info.uid(),
    }


def select_marker_stream(max_wait_seconds=40):
    """Devuelve (inlet, stream_info_dict). El inlet se crea con recover=True."""
    while True:
        streams = _search_streams_with_countdown(max_wait_seconds)

        if not streams:
            print(t("lsl_none"))
            while True:
                print(t("lsl_retry", seconds=int(round(max_wait_seconds))))
                print(t("lsl_continue"))
                choice = input(t("select_option")).strip()
                if choice == "1":
                    print()
                    break
                if choice == "0":
                    _warn_no_lsl()
                    return None, None
                print(t("invalid_10"))
            continue

        print(t("streams_available"))
        for i, stream in enumerate(streams, 1):
            sid = stream.source_id() or "SIN source_id"
            print(
                f" [{i}] {stream.name()} | {stream.type()} | "
                f"{stream.channel_count()} ch | {stream.nominal_srate()} Hz | source_id={sid}"
            )
        print(t("search_again"))
        print(t("lsl_continue"))

        while True:
            choice = input(t("select_stream")).strip()
            if choice.lower() == "r":
                print()
                break
            if choice == "0":
                _warn_no_lsl()
                return None, None
            try:
                choice_num = int(choice)
            except ValueError:
                print(t("invalid"))
                continue

            if 1 <= choice_num <= len(streams):
                selected = streams[choice_num - 1]
                info_dict = stream_info_to_dict(selected)
                print(t("lsl_selected", name=selected.name(), type=selected.type()))
                if not info_dict.get("source_id"):
                    print(t("no_source_id"))
                    print(t("no_source_id_2"))
                    print(t("no_source_id_3"))
                try:
                    # recover=True permite que liblsl intente recuperar la misma fuente cuando
                    # dispone de un source_id estable.
                    return StreamInlet(selected, recover=True), info_dict
                except TypeError:
                    # Compatibilidad con builds antiguos donde recover no es keyword.
                    return StreamInlet(selected), info_dict
                except Exception as exc:
                    print(t("lsl_open_error", error=exc))
                    print(t("lsl_open_error_2"))
            else:
                print(t("lsl_invalid_range", n=len(streams)))


def get_time_correction(inlet, timeout=1.0):
    if inlet is None:
        return 0.0
    try:
        return float(inlet.time_correction(timeout=timeout))
    except Exception as exc:
        print(t("time_correction_error", error=exc))
        return 0.0
