from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EventItem:
    date: str
    level: str
    level_number: int
    provider: str
    event_id: str
    category: str
    message: str
    risk: str
    interpretation: str
    log_name: str
    record_id: str
    computer: str
    process_id: str
    thread_id: str
    raw_xml: str = ""
    timestamp_sort: str = ""

    def detail_text(self) -> str:
        return (
            f"Fecha: {self.date}\n"
            f"Nivel: {self.level}\n"
            f"Registro: {self.log_name}\n"
            f"Origen: {self.provider}\n"
            f"ID Evento: {self.event_id}\n"
            f"Categoría: {self.category}\n"
            f"Equipo: {self.computer}\n"
            f"Record ID: {self.record_id}\n"
            f"Proceso: {self.process_id}\n"
            f"Hilo: {self.thread_id}\n"
            f"Riesgo: {self.risk}\n"
            f"Interpretación: {self.interpretation}\n\n"
            f"Mensaje:\n{self.message}"
        )


@dataclass
class EventResult:
    events: list[EventItem]
    warnings: list[str]
