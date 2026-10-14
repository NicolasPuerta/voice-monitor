"""Servicio de generación de informes de sesión en HTML y PDF (MR 15).

Genera reportes detallados y sanitizados a partir de los datos en SQLite,
utilizando Jinja2 y WeasyPrint cuando están disponibles.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from app.core.privacy import PrivacySanitizer

logger = logging.getLogger(__name__)

HTML_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Informe de Sesión - Ubuntu Voice Monitor</title>
  <style>
    :root {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #1e293b;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --primary: #2563eb;
      --success: #16a34a;
      --warning: #d97706;
      --danger: #dc2626;
      --critical: #991b1b;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      margin: 0;
      padding: 24px;
    }
    .container {
      max-width: 900px;
      margin: 0 auto;
    }
    .header {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
    }
    .header h1 {
      margin: 0 0 8px 0;
      font-size: 24px;
      color: var(--primary);
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .kpi-card {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 16px;
    }
    .kpi-label {
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
    }
    .kpi-value {
      font-size: 20px;
      font-weight: 700;
      margin-top: 4px;
    }
    .section {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px 24px;
      margin-bottom: 24px;
    }
    .section h2 {
      margin: 0 0 16px 0;
      font-size: 18px;
      border-bottom: 2px solid var(--border);
      padding-bottom: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
    }
    th, td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      font-size: 14px;
    }
    th {
      background: var(--bg);
      color: var(--text-muted);
      font-weight: 600;
    }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 600;
    }
    .badge-critical { background: #fee2e2; color: var(--critical); }
    .badge-high { background: #ffedd5; color: var(--danger); }
    .badge-medium { background: #fef3c7; color: var(--warning); }
    .badge-low { background: #dbeafe; color: var(--primary); }
    .badge-info { background: #dcfce7; color: var(--success); }
    .empty-note {
      color: var(--text-muted);
      font-style: italic;
      padding: 12px 0;
    }
    @media print {
      body { background: #fff; padding: 0; }
      .container { max-width: 100%; }
      .section, .header { border: 1px solid #ccc; break-inside: avoid; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Informe de Sesión: {{ data.session_id }}</h1>
      <p style="margin: 0; color: var(--text-muted);">
        Generado el {{ data.generated_at }} | Ubuntu Voice Monitor
      </p>
      <div class="meta-grid">
        <div class="kpi-card">
          <div class="kpi-label">Duración</div>
          <div class="kpi-value">{{ data.duration_str }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Eventos Totales</div>
          <div class="kpi-value">{{ data.total_events }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Pico CPU</div>
          <div class="kpi-value">
            {% if data.cpu_peak is not none %}
              {{ data.cpu_peak }}%
            {% else %}
              No registrado
            {% endif %}
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Pico Memoria</div>
          <div class="kpi-value">
            {% if data.memory_peak is not none %}
              {{ data.memory_peak }}%
            {% else %}
              No registrado
            {% endif %}
          </div>
        </div>
      </div>
    </div>

    <!-- Resumen y Nivel de Confianza -->
    <div class="section">
      <h2>Resumen Ejecutivo y Confianza</h2>
      <p><strong>Resumen:</strong> {{ data.summary }}</p>
      <p>
        <strong>Nivel de Confianza Global:</strong>
        <span class="badge badge-info">{{ data.confidence_level|upper }}</span>
        (Alta: {{ data.confidence_counts.get('alta', 0) }},
         Media: {{ data.confidence_counts.get('media', 0) }},
         Baja: {{ data.confidence_counts.get('baja', 0) }})
      </p>
    </div>

    <!-- Aplicaciones Principales -->
    <div class="section">
      <h2>Aplicaciones Principales Observadas</h2>
      {% if data.top_applications %}
      <table>
        <thead>
          <tr>
            <th>Aplicación</th>
            <th>Eventos</th>
            <th>Severidad Máxima</th>
            <th>Impacto Máx</th>
          </tr>
        </thead>
        <tbody>
          {% for app in data.top_applications %}
          <tr>
            <td><strong>{{ app.name }}</strong></td>
            <td>{{ app.count }}</td>
            <td>
              <span class="badge badge-{{ app.max_severity|lower }}">
                {{ app.max_severity }}
              </span>
            </td>
            <td>{{ app.max_impact|round(1) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-note">No se registraron aplicaciones con eventos relevantes.</div>
      {% endif %}
    </div>

    <!-- Eventos Inusuales y Riesgos -->
    <div class="section">
      <h2>Eventos Inusuales y Riesgos Detectados</h2>
      {% if data.unusual_events %}
      <table>
        <thead>
          <tr>
            <th>Hora</th>
            <th>Tipo</th>
            <th>Severidad</th>
            <th>Resumen</th>
            <th>Riesgo</th>
          </tr>
        </thead>
        <tbody>
          {% for ev in data.unusual_events %}
          <tr>
            <td style="white-space: nowrap;">{{ ev.time }}</td>
            <td><code>{{ ev.type }}</code></td>
            <td>
              <span class="badge badge-{{ ev.severity|lower }}">
                {{ ev.severity }}
              </span>
            </td>
            <td>{{ ev.summary }}</td>
            <td>{{ ev.risk }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-note">No se registraron eventos inusuales ni de alto riesgo.</div>
      {% endif %}
    </div>

    <!-- Procesos Abiertos / Cerrados -->
    <div class="section">
      <h2>Actividad de Procesos (Abiertos / Cerrados)</h2>
      {% if data.process_activity %}
      <table>
        <thead>
          <tr>
            <th>Hora</th>
            <th>Tipo</th>
            <th>Proceso / Detalle</th>
          </tr>
        </thead>
        <tbody>
          {% for p in data.process_activity %}
          <tr>
            <td style="white-space: nowrap;">{{ p.time }}</td>
            <td>{{ p.type }}</td>
            <td>{{ p.detail }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-note">
        Sin cambios anómalos de procesos registrados durante la sesión.
      </div>
      {% endif %}
    </div>

    <!-- Periodos No Molestar (DND) -->
    <div class="section">
      <h2>Periodos y Supresiones No Molestar (DND)</h2>
      {% if data.dnd_periods %}
      <table>
        <thead>
          <tr>
            <th>Hora</th>
            <th>Motivo de Supresión</th>
            <th>Evento Afectado</th>
          </tr>
        </thead>
        <tbody>
          {% for dnd in data.dnd_periods %}
          <tr>
            <td style="white-space: nowrap;">{{ dnd.time }}</td>
            <td><code>{{ dnd.reason }}</code></td>
            <td>{{ dnd.summary }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-note">No se registraron periodos de supresión DND.</div>
      {% endif %}
    </div>

    <!-- Fuentes Degradadas -->
    <div class="section">
      <h2>Estado de Fuentes y Degradación</h2>
      {% if data.degraded_sources %}
      <table>
        <thead>
          <tr>
            <th>Fuente</th>
            <th>Estado</th>
            <th>Motivo</th>
            <th>Hora</th>
          </tr>
        </thead>
        <tbody>
          {% for src in data.degraded_sources %}
          <tr>
            <td><strong>{{ src.source }}</strong></td>
            <td><span class="badge badge-high">{{ src.state }}</span></td>
            <td>{{ src.reason }}</td>
            <td>{{ src.updated_at }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-note">
        Todas las fuentes operaron normalmente sin degradación.
      </div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""


@dataclass
class SessionReportData:
    """Estructura de datos agregados para la generación del informe de sesión."""

    session_id: str
    started_at: str
    ended_at: str | None
    duration_str: str
    total_events: int
    top_applications: list[dict[str, Any]]
    cpu_peak: float | None
    memory_peak: float | None
    process_activity: list[dict[str, Any]]
    unusual_events: list[dict[str, Any]]
    dnd_periods: list[dict[str, Any]]
    degraded_sources: list[dict[str, Any]]
    summary: str
    confidence_level: str
    confidence_counts: dict[str, int] = field(default_factory=dict)
    decisions_breakdown: dict[str, int] = field(default_factory=dict)
    generated_at: str = ""


class ReportService:
    """Genera informes HTML y PDF estructurados a partir de SQLite."""

    def __init__(
        self,
        db_path: Path | str,
        sanitizer: PrivacySanitizer | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.sanitizer = sanitizer or PrivacySanitizer()

    def fetch_report_data(
        self, session_id: str | None = None
    ) -> SessionReportData:
        """Extrae y agrega los datos de la sesión desde la base de datos."""
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Base de datos no encontrada en {self.db_path}"
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 1. Obtener la sesión especificada o la más reciente
            if session_id:
                cur = conn.execute(
                    "SELECT id, started_at, ended_at FROM sessions WHERE id = ?",
                    (session_id,),
                )
                session_row = cur.fetchone()
            else:
                cur = conn.execute(
                    "SELECT id, started_at, ended_at FROM sessions "
                    "ORDER BY started_at DESC LIMIT 1"
                )
                session_row = cur.fetchone()

            if not session_row:
                # Si no hay sesiones registradas pero hay eventos huérfanos
                cur = conn.execute(
                    "SELECT session_id FROM events ORDER BY detected_at DESC LIMIT 1"
                )
                orphan_row = cur.fetchone()
                if orphan_row:
                    effective_id = orphan_row["session_id"]
                    session_row = {
                        "id": effective_id,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "ended_at": None,
                    }
                else:
                    raise ValueError(
                        f"No se encontró sesión registrada: {session_id or 'reciente'}"
                    )

            target_session_id = session_row["id"]
            started_at_str = session_row["started_at"]
            ended_at_str = session_row["ended_at"]

            # Calcular duración
            duration_str = self._calculate_duration(started_at_str, ended_at_str)

            # 2. Consultar eventos de la sesión
            events_cur = conn.execute(
                """
                SELECT id, event_type, severity, confidence, decision, score,
                       impact, novelty, anomaly, risk, detected_at, app_key,
                       summary, metadata_json
                FROM events
                WHERE session_id = ?
                ORDER BY detected_at ASC
                """,
                (target_session_id,),
            )
            event_rows = [dict(r) for r in events_cur.fetchall()]

            # 3. Consultar salud de fuentes de la sesión
            health_cur = conn.execute(
                """
                SELECT source, state, reason, updated_at
                FROM source_health
                WHERE session_id = ?
                ORDER BY updated_at ASC
                """,
                (target_session_id,),
            )
            health_rows = [dict(r) for r in health_cur.fetchall()]

            # 4. Consultar agregados por minuto si existen
            agg_cur = conn.execute(
                """
                SELECT metric_name, MAX(max_val) as peak
                FROM minute_agg
                WHERE session_id = ?
                GROUP BY metric_name
                """,
                (target_session_id,),
            )
            minute_peaks = {r["metric_name"]: r["peak"] for r in agg_cur.fetchall()}

        return self._build_report_data(
            target_session_id,
            started_at_str,
            ended_at_str,
            duration_str,
            event_rows,
            health_rows,
            minute_peaks,
        )

    def _calculate_duration(
        self, started_at_str: str, ended_at_str: str | None
    ) -> str:
        """Calcula la duración amigable en horas, minutos y segundos."""
        try:
            start_dt = datetime.fromisoformat(started_at_str)
            if ended_at_str:
                end_dt = datetime.fromisoformat(ended_at_str)
                secs = max(0, int((end_dt - start_dt).total_seconds()))
                status = ""
            else:
                now_dt = datetime.now(timezone.utc)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                secs = max(0, int((now_dt - start_dt).total_seconds()))
                status = " (en curso)"

            hours = secs // 3600
            mins = (secs % 3600) // 60
            remaining_secs = secs % 60
            if hours > 0:
                return f"{hours}h {mins}m {remaining_secs}s{status}"
            return f"{mins}m {remaining_secs}s{status}"
        except Exception:
            return "No disponible"

    def _build_report_data(
        self,
        session_id: str,
        started_at: str,
        ended_at: str | None,
        duration_str: str,
        events: list[dict[str, Any]],
        health_rows: list[dict[str, Any]],
        minute_peaks: dict[str, float],
    ) -> SessionReportData:
        """Procesa, agrupa y sanitiza todas las secciones del informe."""
        total_events = len(events)
        confidence_counts: dict[str, int] = {"alta": 0, "media": 0, "baja": 0}
        decisions_breakdown: dict[str, int] = {}

        app_stats: dict[str, dict[str, Any]] = {}
        unusual_events: list[dict[str, Any]] = []
        process_activity: list[dict[str, Any]] = []
        dnd_periods: list[dict[str, Any]] = []

        cpu_peak: float | None = minute_peaks.get("cpu")
        memory_peak: float | None = minute_peaks.get("memory")

        severity_rank = {
            "CRITICAL": 5,
            "HIGH": 4,
            "MEDIUM": 3,
            "LOW": 2,
            "INFO": 1,
        }

        for ev in events:
            # Confianza
            conf = (ev.get("confidence") or "media").lower()
            confidence_counts[conf] = confidence_counts.get(conf, 0) + 1

            # Decisión
            dec = ev.get("decision") or "UNKNOWN"
            decisions_breakdown[dec] = decisions_breakdown.get(dec, 0) + 1

            # Parsear metadata JSON de forma segura
            meta: dict[str, Any] = {}
            if ev.get("metadata_json"):
                try:
                    meta = json.loads(ev["metadata_json"])
                except Exception:
                    meta = {}

            # Extraer picos de CPU / RAM si no estaban en minute_agg
            if "cpu_percent" in meta and isinstance(meta["cpu_percent"], (int, float)):
                c_val = float(meta["cpu_percent"])
                cpu_peak = max(cpu_peak or 0.0, c_val)
            if "memory_percent" in meta and isinstance(
                meta["memory_percent"], (int, float)
            ):
                m_val = float(meta["memory_percent"])
                memory_peak = max(memory_peak or 0.0, m_val)

            # Sanitización del resumen y app_key
            sanitized_summary = self.sanitizer.sanitize_text(ev.get("summary") or "")
            app_raw = ev.get("app_key") or "Sistema"
            sanitized_app = self.sanitizer.sanitize_text(app_raw) or "Sistema"

            # Agrupación de aplicaciones principales
            if sanitized_app not in app_stats:
                app_stats[sanitized_app] = {
                    "name": sanitized_app,
                    "count": 0,
                    "max_severity": "INFO",
                    "max_impact": 0.0,
                }
            st = app_stats[sanitized_app]
            st["count"] += 1
            cur_sev = ev.get("severity") or "INFO"
            if severity_rank.get(cur_sev, 0) > severity_rank.get(
                st["max_severity"], 0
            ):
                st["max_severity"] = cur_sev
            ev_impact = ev.get("impact") or 0.0
            st["max_impact"] = max(st["max_impact"], float(ev_impact))

            # Eventos inusuales y riesgos
            sev = ev.get("severity", "INFO")
            risk = ev.get("risk")
            anomaly = ev.get("anomaly")
            is_unusual = (
                sev in ("CRITICAL", "HIGH")
                or (risk is not None and float(risk) >= 0.5)
                or (anomaly is not None and float(anomaly) >= 0.5)
            )
            if is_unusual:
                time_str = ev.get("detected_at", "")[:19].replace("T", " ")
                unusual_events.append(
                    {
                        "time": time_str,
                        "type": ev.get("event_type", ""),
                        "severity": sev,
                        "summary": sanitized_summary,
                        "risk": f"{float(risk):.2f}" if risk is not None else "N/A",
                    }
                )

            # Actividad de procesos (abiertos/cerrados/zombies)
            ev_type = ev.get("event_type", "")
            if ev_type in (
                "process_started",
                "process_exited",
                "process_died",
                "zombie_process",
            ):
                time_str = ev.get("detected_at", "")[:19].replace("T", " ")
                process_activity.append(
                    {
                        "time": time_str,
                        "type": ev_type,
                        "detail": sanitized_summary,
                    }
                )

            # Periodos No Molestar (DND)
            if dec == "DND" or meta.get("dnd_suppressed") == "true":
                time_str = ev.get("detected_at", "")[:19].replace("T", " ")
                dnd_reason = meta.get("dnd_reason", "manual")
                dnd_periods.append(
                    {
                        "time": time_str,
                        "reason": self.sanitizer.sanitize_text(dnd_reason),
                        "summary": sanitized_summary,
                    }
                )

        # Aplicaciones ordenadas por impacto y cantidad de eventos
        top_applications = sorted(
            app_stats.values(),
            key=lambda x: (severity_rank.get(x["max_severity"], 0), x["count"]),
            reverse=True,
        )[:8]

        # Fuentes degradadas
        degraded_sources: list[dict[str, Any]] = []
        for h in health_rows:
            if h.get("state") != "OK":
                degraded_sources.append(
                    {
                        "source": h.get("source", ""),
                        "state": h.get("state", ""),
                        "reason": self.sanitizer.sanitize_text(
                            h.get("reason") or "Falla registrada"
                        ),
                        "updated_at": (h.get("updated_at") or "")[:19].replace(
                            "T", " "
                        ),
                    }
                )

        # Nivel de confianza global
        if confidence_counts.get("alta", 0) >= max(
            confidence_counts.get("media", 0), confidence_counts.get("baja", 0)
        ):
            confidence_level = "alta"
        elif confidence_counts.get("media", 0) >= confidence_counts.get("baja", 0):
            confidence_level = "media"
        else:
            confidence_level = "baja"

        # Resumen general
        spoken_count = decisions_breakdown.get("SPOKEN", 0)
        dnd_count = len(dnd_periods)
        summary = (
            f"Sesión con duración de {duration_str}. Se observaron {total_events} "
            f"eventos ({spoken_count} narrados por voz, "
            f"{dnd_count} gestionados bajo DND). "
            f"Se registraron {len(unusual_events)} eventos inusuales o de riesgo."
        )

        return SessionReportData(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_str=duration_str,
            total_events=total_events,
            top_applications=top_applications,
            cpu_peak=round(cpu_peak, 1) if cpu_peak is not None else None,
            memory_peak=round(memory_peak, 1) if memory_peak is not None else None,
            process_activity=process_activity,
            unusual_events=unusual_events,
            dnd_periods=dnd_periods,
            degraded_sources=degraded_sources,
            summary=summary,
            confidence_level=confidence_level,
            confidence_counts=confidence_counts,
            decisions_breakdown=decisions_breakdown,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    def generate_html(self, session_id: str | None = None) -> str:
        """Compila y renderiza el informe en formato HTML mediante Jinja2."""
        data = self.fetch_report_data(session_id)

        try:
            import jinja2

            template = jinja2.Template(HTML_REPORT_TEMPLATE, autoescape=True)
            return str(template.render(data=data))
        except ImportError:
            # Fallback simple en caso de ausencia de Jinja2
            return (
                f"<html><body><h1>Informe {data.session_id}</h1>"
                f"<p>{data.summary}</p></body></html>"
            )

    def save_html(
        self, output_path: Path | str, session_id: str | None = None
    ) -> Path:
        """Guarda el informe HTML generado en el archivo especificado."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        html = self.generate_html(session_id)
        out.write_text(html, encoding="utf-8")
        logger.info("Informe HTML guardado en: %s", out)
        return out

    def generate_pdf(self, session_id: str | None = None) -> bytes:
        """Genera el informe en formato PDF utilizando WeasyPrint si está disponible."""
        html_content = self.generate_html(session_id)
        try:
            import weasyprint  # type: ignore[import-not-found]

            weasy_doc = weasyprint.HTML(string=html_content)
            return weasy_doc.write_pdf()  # type: ignore[no-any-return]
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "WeasyPrint no está disponible para generar el informe PDF. "
                "Para habilitar informes PDF instale weasyprint: pip install weasyprint"
            ) from exc

    def save_pdf(
        self, output_path: Path | str, session_id: str | None = None
    ) -> Path:
        """Genera y guarda el informe PDF en la ruta especificada."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = self.generate_pdf(session_id)
        out.write_bytes(pdf_bytes)
        logger.info("Informe PDF guardado en: %s", out)
        return out
