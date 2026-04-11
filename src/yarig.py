from __future__ import annotations

"""Yarig.ai integration — full platform access via API."""

import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from zoneinfo import ZoneInfo
import aiohttp

from src.config import YARIG_EMAIL, YARIG_PASSWORD

logger = logging.getLogger(__name__)

YARIG_BASE = "https://yarig.ai"
LOGIN_URL = f"{YARIG_BASE}/registration/login"
TASKS_URL = f"{YARIG_BASE}/tasks/json_get_current_day_tasks_and_journey_info"
ADD_TASKS_URL = f"{YARIG_BASE}/tasks/json_add_tasks"
UPDATE_TASK_URL = f"{YARIG_BASE}/tasks/json_update_task"
DELETE_TASK_URL = f"{YARIG_BASE}/tasks/json_delete_task"
OPEN_TASK_URL = f"{YARIG_BASE}/tasks/json_get_and_open_task"
CLOSE_TASK_URL = f"{YARIG_BASE}/tasks/json_close_task"
CLOCKING_URL = f"{YARIG_BASE}/clocking/json_add_clocking"
CLOCKING_EXTRA_URL = f"{YARIG_BASE}/clocking_extra/json_add_clocking_extra"
SCORE_URL = f"{YARIG_BASE}/score/json_user_score"
USERS_URL = f"{YARIG_BASE}/user/json_get_customers_and_mates_like"
PROJECTS_URL = f"{YARIG_BASE}/projects/json_get_projects_like_by_customer_and_order"
ADD_REQUEST_URL = f"{YARIG_BASE}/tasks/json_add_request"
NOTIFICATIONS_URL = f"{YARIG_BASE}/system_notification/json_get_user_notifications"
WORKING_STATE_URL = f"{YARIG_BASE}/working_state/json_change_state"

UTC = timezone.utc
DISPLAY_TZ = ZoneInfo("Europe/Madrid")


def _task_sort_key(task: dict) -> tuple[int, str]:
    finished = task.get("finished", "0") == "1"
    started = bool(task.get("start_time"))
    ended = bool(task.get("end_time"))
    if started and not ended and not finished:
        rank = 0
    elif not started and not finished:
        rank = 1
    elif started and ended and not finished:
        rank = 2
    else:
        rank = 3
    return rank, str(task.get("description", "")).lower()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _format_elapsed_compact(start_value: str | None, end_value: str | None = None) -> str:
    start_dt = _parse_dt(start_value)
    if start_dt is None:
        return ""
    end_dt = _parse_dt(end_value) if end_value else datetime.now(UTC)
    if end_dt is None:
        end_dt = datetime.now(UTC)
    total_seconds = max(int((end_dt - start_dt).total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def _format_panel_timestamp() -> str:
    return datetime.now(DISPLAY_TZ).strftime("%d/%m/%Y %H:%M")


def _clean_html_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_login_error_text(text: str) -> str:
    cleaned = _clean_html_text(text)
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    translations = (
        ("email field must contain a valid email address", "el email de Yarig.ai no es valido; usa una direccion completa"),
        ("email field is required", "falta el email de Yarig.ai"),
        ("password field is required", "falta la contrasena de Yarig.ai"),
        ("these credentials do not match", "las credenciales de Yarig.ai no son correctas"),
        ("invalid email or password", "las credenciales de Yarig.ai no son correctas"),
    )
    for needle, replacement in translations:
        if needle in lowered:
            return replacement
    return cleaned


def _extract_login_error_text(body: str) -> str:
    matches = re.findall(
        r'<p[^>]+class=["\'][^"\']*clue-error[^"\']*["\'][^>]*>(.*?)</p>',
        body or "",
        re.IGNORECASE | re.DOTALL,
    )
    errors: list[str] = []
    for match in matches:
        cleaned = _normalize_login_error_text(match)
        if cleaned and cleaned not in errors:
            errors.append(cleaned)
    return " ".join(errors[:2])


class YarigClient:
    """Async client for Yarig.ai with full platform access."""

    def __init__(self, email: str = YARIG_EMAIL, password: str = YARIG_PASSWORD):
        self.email = email
        self.password = password
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False
        self._last_error_code = ""
        self._last_error_status: int | None = None
        self._last_error_url = ""
        self._last_error_detail = ""

    def credentials_configured(self) -> bool:
        return bool(self.email and self.password)

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
            self._logged_in = False

    @staticmethod
    def _looks_like_login_page(text: str) -> bool:
        snippet = text.lower()
        return "name=\"email\"" in snippet and "name=\"password\"" in snippet and "/registration/login" in snippet

    def _clear_error(self) -> None:
        self._last_error_code = ""
        self._last_error_status = None
        self._last_error_url = ""
        self._last_error_detail = ""

    def _remember_error(
        self,
        code: str,
        *,
        url: str = "",
        status: int | None = None,
        detail: str = "",
    ) -> None:
        self._last_error_code = code
        self._last_error_status = status
        self._last_error_url = url
        self._last_error_detail = detail

    def _error_detail_text(self) -> str:
        code = self._last_error_code
        if code == "missing_credentials":
            return "faltan las credenciales YARIG_EMAIL/YARIG_PASSWORD"
        if code == "timeout":
            return "Yarig.ai esta tardando demasiado en responder"
        if code == "network":
            return "no se ha podido abrir conexion con Yarig.ai"
        if code == "login_failed":
            if self._last_error_detail:
                return self._last_error_detail
            return "el login de Yarig.ai ha sido rechazado"
        if code == "session_expired":
            return "la sesion de Yarig.ai ha expirado y no se ha podido renovar"
        if code == "http_status" and self._last_error_status:
            return f"Yarig.ai ha respondido con error {self._last_error_status}"
        if code == "invalid_json":
            return "Yarig.ai ha devuelto una respuesta inesperada"
        if code == "unexpected":
            return "se ha producido un error inesperado hablando con Yarig.ai"
        return "ha habido un problema desconocido al hablar con Yarig.ai"

    def operation_error(self, action: str, *, prefix: str = "⚠️") -> str:
        detail = self._error_detail_text()
        if prefix:
            return f"{prefix} No se pudo {action}: {detail}."
        return f"No se pudo {action}: {detail}."

    async def login(self) -> bool:
        if not self.credentials_configured():
            logger.warning("Yarig credentials not configured")
            self._remember_error("missing_credentials", url=LOGIN_URL)
            return False
        await self._ensure_session()
        try:
            await self._session.get(LOGIN_URL)
            async with self._session.post(
                LOGIN_URL,
                data={"email": self.email, "password": self.password, "submit": "Entrar"},
                allow_redirects=True,
            ) as resp:
                body = await resp.text()
                final_url = str(resp.url)
                if resp.status == 200 and (
                    "/tasks" in final_url or
                    "/dashboard" in final_url or
                    "Mis tareas" in body or
                    "task-day-resume" in body
                ):
                    self._logged_in = True
                    self._clear_error()
                    logger.info("Yarig login successful")
                    return True
                self._logged_in = False
                detail = _extract_login_error_text(body) or final_url
                self._remember_error("login_failed", url=LOGIN_URL, status=resp.status, detail=detail)
                logger.warning("Yarig login failed: status=%s url=%s detail=%s", resp.status, resp.url, detail)
                return False
        except aiohttp.ClientConnectionError as exc:
            self._logged_in = False
            self._remember_error("network", url=LOGIN_URL, detail=str(exc))
            logger.warning("Yarig login network error: %s", exc)
            return False
        except aiohttp.ClientError as exc:
            self._logged_in = False
            self._remember_error("network", url=LOGIN_URL, detail=str(exc))
            logger.warning("Yarig login client error: %s", exc)
            return False
        except Exception as e:
            self._logged_in = False
            self._remember_error("unexpected", url=LOGIN_URL, detail=str(e))
            logger.warning("Yarig login error: %s", e)
            return False

    async def _request(self, url: str, data: dict | None = None, method: str = "POST") -> dict | list | int | None:
        await self._ensure_session()
        if not self._logged_in:
            if not await self.login():
                return None
        try:
            kw = {"data": data} if data else {}
            async with self._session.request(method, url, **kw) as resp:
                body = await resp.text()
                if resp.status == 200 and not self._looks_like_login_page(body):
                    try:
                        result = await resp.json(content_type=None)
                        self._clear_error()
                        return result
                    except Exception as exc:
                        self._remember_error("invalid_json", url=url, detail=str(exc))
                        logger.warning("Yarig JSON parse error for %s: %s", url, exc)
                        return None
                # Session expired
                self._logged_in = False
                if resp.status != 200:
                    self._remember_error("http_status", url=url, status=resp.status, detail=str(resp.url))
                else:
                    self._remember_error(
                        "session_expired",
                        url=url,
                        status=resp.status,
                        detail=_extract_login_error_text(body) or str(resp.url),
                    )
                if await self.login():
                    async with self._session.request(method, url, **kw) as retry:
                        retry_body = await retry.text()
                        if retry.status == 200 and not self._looks_like_login_page(retry_body):
                            try:
                                result = await retry.json(content_type=None)
                                self._clear_error()
                                return result
                            except Exception as exc:
                                self._remember_error("invalid_json", url=url, detail=str(exc))
                                logger.warning("Yarig retry JSON parse error for %s: %s", url, exc)
                                return None
                        if retry.status != 200:
                            self._remember_error("http_status", url=url, status=retry.status, detail=str(retry.url))
                        else:
                            self._remember_error(
                                "session_expired",
                                url=url,
                                status=retry.status,
                                detail=_extract_login_error_text(retry_body) or str(retry.url),
                            )
                            logger.warning(f"Yarig retry returned login page: {url}")
                            return None
                logger.warning(f"Yarig request failed: {url} status={resp.status}")
                return None
        except aiohttp.ClientConnectionError as exc:
            self._remember_error("network", url=url, detail=str(exc))
            logger.warning("Yarig request network error: %s", exc)
            return None
        except aiohttp.ClientError as exc:
            self._remember_error("network", url=url, detail=str(exc))
            logger.warning("Yarig request client error: %s", exc)
            return None
        except Exception as e:
            self._remember_error("unexpected", url=url, detail=str(e))
            logger.warning("Yarig request error: %s", e)
            return None

    @staticmethod
    def _esc(text: str) -> str:
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, f"\\{ch}")
        return text

    # ── Tareas del día ──────────────────────────────────────

    async def get_today_data(self) -> dict | None:
        return await self._request(TASKS_URL)

    async def get_today_summary(self, data: dict | None = None) -> str:
        data = data or await self.get_today_data()
        if not data:
            if not self.credentials_configured():
                return "⚠️ Faltan las credenciales de Yarig.ai en el .env de Memorizer."
            return self.operation_error("cargar el panel de Yarig.ai")

        tasks = data.get("tasks", [])
        clocking = data.get("clocking", [])

        if not tasks and not clocking:
            return "📭 Hoy no hay tareas ni jornada en Yarig.ai"

        active_count = sum(
            1 for task in tasks
            if task.get("start_time") and not task.get("end_time") and task.get("finished", "0") == "0"
        )
        paused_count = sum(
            1 for task in tasks
            if task.get("start_time") and task.get("end_time") and task.get("finished", "0") == "0"
        )
        pending_count = sum(
            1 for task in tasks
            if not task.get("start_time") and task.get("finished", "0") == "0"
        )
        finished_count = sum(1 for task in tasks if task.get("finished", "0") == "1")

        lines = [
            "🗂️ *Tareas del día (Yarig.ai)*",
            f"🟢 {active_count} activas · 🕓 {pending_count} pendientes · ⏸️ {paused_count} pausadas · ✅ {finished_count} completadas",
            f"🔄 Última actualización: {_format_panel_timestamp()}",
            "",
        ]

        ordered_tasks = sorted(tasks, key=_task_sort_key)

        for i, task in enumerate(ordered_tasks, 1):
            desc = self._esc(task.get("description", "").strip())
            project = self._esc(task.get("project", ""))
            finished = task.get("finished", "0")
            start = task.get("start_time")
            end = task.get("end_time")

            if finished == "1":
                status = "✅"
            elif start and not end:
                status = "🟢"
            elif start and end:
                status = "⏸️"
            else:
                status = "🕓"

            line = f"{i}. {status} {desc}"
            if project:
                line += f" — _{project}_"
            elapsed = _format_elapsed_compact(start, end if finished == "1" or end else None)
            if elapsed:
                line += f" · ⏱️ {elapsed}"
            lines.append(line)

        if not tasks:
            lines.append("▫️ Sin tareas registradas")

        if clocking:
            entry = clocking[0]
            name = self._esc(entry.get("name", ""))
            dt = entry.get("datetime", "?")
            lines.append(f"\n🕘 Jornada de *{name}* iniciada: {dt}")

        return "\n".join(lines)

    # ── Fichar ──────────────────────────────────────────────

    async def fichar_entrada(self) -> str:
        result = await self._request(CLOCKING_URL, {"type": 0, "todo": ""})
        if result:
            return "✅ Jornada iniciada"
        return self.operation_error("fichar la entrada")

    async def fichar_salida(self, todo: str = "") -> str:
        result = await self._request(CLOCKING_URL, {"type": 1, "todo": todo})
        if result:
            return "✅ Jornada finalizada"
        return self.operation_error("fichar la salida")

    # ── Horas extras ────────────────────────────────────────

    async def extras_inicio(self) -> str:
        result = await self._request(CLOCKING_EXTRA_URL, {"type": 0})
        msgs = {
            0: "⚠️ Estás dentro de tu horario laboral, no puedes hacer extras ahora",
            1: "⚠️ Ya tienes una jornada extra abierta, ciérrala primero",
        }
        if isinstance(result, int) and result in msgs:
            return msgs[result]
        return "✅ Jornada de horas extras iniciada"

    async def extras_fin(self) -> str:
        result = await self._request(CLOCKING_EXTRA_URL, {"type": 1})
        msgs = {
            2: "✅ Jornada de horas extras finalizada",
            3: "⚠️ Ya finalizaste las horas extras hoy",
        }
        if isinstance(result, int) and result in msgs:
            return msgs[result]
        return "⚠️ Hoy no has iniciado horas extras"

    # ── Añadir tarea ────────────────────────────────────────

    async def add_task(self, description: str, project_id: int = 312, estimation: int = 1) -> str:
        tmp_id = int(time.time() * 1000)
        task_str = f"{tmp_id}#$#{estimation}#$#{description}#$#{project_id}@$@"
        result = await self._request(ADD_TASKS_URL, {"tasks": task_str})
        if result:
            return f"✅ Tarea añadida: {description}"
        return self.operation_error("crear la tarea")

    # ── Iniciar / Parar tarea ───────────────────────────────

    def _find_active_task(self, tasks: list[dict]) -> dict | None:
        """Find the currently active (started, not finished) task."""
        for t in tasks:
            if t.get("start_time") and not t.get("end_time") and t.get("finished") == "0":
                return t
        return None

    async def iniciar_tarea(self, task_index: int = 1) -> str:
        """Start or resume a task by index."""
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        tasks = sorted(data["tasks"], key=_task_sort_key)
        if task_index < 1 or task_index > len(tasks):
            return f"⚠️ Tarea {task_index} no existe (hay {len(tasks)})"

        task = tasks[task_index - 1]
        tid = task["id"]
        result = await self._request(OPEN_TASK_URL, {"id": tid})
        if result:
            desc = task.get("description", "").strip()
            was_started = task.get("start_time") is not None
            icon = "🔄" if was_started else "▶️"
            verb = "Reanudada" if was_started else "Iniciada"
            return f"{icon} Tarea {verb}: {desc}"
        return self.operation_error("poner en marcha la tarea")

    async def iniciar_tarea_por_id(self, task_id: str) -> str:
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        task = next((t for t in data["tasks"] if str(t.get("id")) == str(task_id)), None)
        if not task:
            return "⚠️ Esa tarea ya no aparece en la lista actual"

        result = await self._request(OPEN_TASK_URL, {"id": task_id})
        if result:
            desc = task.get("description", "").strip()
            was_started = task.get("start_time") is not None
            icon = "🔄" if was_started else "▶️"
            verb = "Reanudada" if was_started else "Iniciada"
            return f"{icon} Tarea {verb}: {desc}"
        return self.operation_error("poner en marcha la tarea")

    async def pausar_tarea(self) -> str:
        """Pause the active task (leave for later, not finished)."""
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        active = self._find_active_task(data["tasks"])
        if not active:
            return "⚠️ No hay ninguna tarea en curso"

        tid = active["id"]
        # finished=0 → pause (dejar para luego)
        result = await self._request(CLOSE_TASK_URL, {"tid": tid, "finished": 0})
        if result is not None:
            desc = active.get("description", "").strip()
            return f"⏸ Tarea pausada: {desc}\nUsa /iniciar para reanudarla"
        return self.operation_error("pausar la tarea")

    async def pausar_tarea_por_id(self, task_id: str) -> str:
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        task = next((t for t in data["tasks"] if str(t.get("id")) == str(task_id)), None)
        if not task:
            return "⚠️ Esa tarea ya no aparece en la lista actual"

        result = await self._request(CLOSE_TASK_URL, {"tid": task_id, "finished": 0})
        if result is not None:
            desc = task.get("description", "").strip()
            return f"⏸ Tarea pausada: {desc}\nUsa /iniciar para reanudarla"
        return self.operation_error("pausar la tarea")

    async def finalizar_tarea(self, task_index: int | None = None) -> str:
        """Finish/complete a task (mark as done)."""
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        tasks = sorted(data["tasks"], key=_task_sort_key)

        if task_index is not None:
            if task_index < 1 or task_index > len(tasks):
                return f"⚠️ Tarea {task_index} no existe (hay {len(tasks)})"
            task = tasks[task_index - 1]
        else:
            task = self._find_active_task(tasks)
            if not task:
                return "⚠️ No hay ninguna tarea en curso. Usa /finalizar <n> para indicar cuál"

        tid = task["id"]
        # finished=1 → completar
        result = await self._request(CLOSE_TASK_URL, {"tid": tid, "finished": 1})
        if result is not None:
            desc = task.get("description", "").strip()
            return f"✅ Tarea finalizada: {desc}"
        return self.operation_error("finalizar la tarea")

    async def finalizar_tarea_por_id(self, task_id: str) -> str:
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        task = next((t for t in data["tasks"] if str(t.get("id")) == str(task_id)), None)
        if not task:
            return "⚠️ Esa tarea ya no aparece en la lista actual"

        result = await self._request(CLOSE_TASK_URL, {"tid": task_id, "finished": 1})
        if result is not None:
            desc = task.get("description", "").strip()
            return f"✅ Tarea finalizada: {desc}"
        return self.operation_error("finalizar la tarea")

    # ── Puntuación ──────────────────────────────────────────

    async def get_score(self) -> str:
        result = await self._request(SCORE_URL)
        if result is not None:
            score = int(result) if isinstance(result, (int, str)) else 0
            emoji = "🏅" if score > 0 else "📉" if score < 0 else "➖"
            return f"{emoji} Tu puntuación en Yarig: *{score}* puntos"
        return self.operation_error("obtener la puntuacion")

    # ── Equipo ──────────────────────────────────────────────

    async def get_team(self) -> str:
        result = await self._request(USERS_URL, {"term": ""})
        if not result or not result.get("mates"):
            return self.operation_error("obtener el equipo")

        mates = result["mates"]
        lines = [f"🤝 *Equipo Yarig.ai* ({len(mates)} miembros)\n"]
        for m in mates:
            name = self._esc(m.get("name", "?"))
            lines.append(f"• {name}")
        return "\n".join(lines)

    # ── Historial ───────────────────────────────────────────

    async def get_history(self) -> str:
        import re
        await self._ensure_session()
        if not self._logged_in:
            if not await self.login():
                return self.operation_error("abrir el historial")

        try:
            async with self._session.get(f"{YARIG_BASE}/tasks/history") as resp:
                if resp.status != 200:
                    self._remember_error("http_status", url=f"{YARIG_BASE}/tasks/history", status=resp.status, detail=str(resp.url))
                    return self.operation_error("obtener el historial")
                html = await resp.text()

            # Parse table rows
            rows = re.findall(
                r'<tr[^>]*class="task-row[^"]*"[^>]*>(.*?)</tr>',
                html, re.DOTALL
            )
            if not rows:
                # Try simpler pattern
                rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)

            # Extract task descriptions from HTML
            tasks_found = []
            for row in rows[:20]:
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                if len(cells) >= 3:
                    # Clean HTML tags
                    clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                    clean = [c for c in clean if c]
                    if clean:
                        tasks_found.append(clean)

            if not tasks_found:
                return "📜 Sin historial de tareas reciente"

            lines = ["📜 *Historial de tareas*\n"]
            for t in tasks_found[:10]:
                desc = self._esc(" | ".join(t[:3]))
                lines.append(f"• {desc}")

            return "\n".join(lines)
        except Exception as e:
            self._remember_error("unexpected", url=f"{YARIG_BASE}/tasks/history", detail=str(e))
            logger.warning("History error: %s", e)
            return self.operation_error("obtener el historial")

    # ── Pedir tarea a compañero ─────────────────────────────

    async def find_mate(self, name: str) -> dict | None:
        result = await self._request(USERS_URL, {"term": name})
        if not result or not result.get("mates"):
            return None
        mates = result["mates"]
        # Fuzzy match
        name_lower = name.lower()
        for m in mates:
            if name_lower in m.get("name", "").lower():
                return m
        return mates[0] if mates else None

    async def send_request(self, user_id: str, text: str, req_type: int = 2) -> str:
        result = await self._request(ADD_REQUEST_URL, {
            "addressees": user_id,
            "text": text,
            "type": req_type,
        })
        if result:
            types = {1: "Sugerencia", 2: "Petición", 3: "Urgencia"}
            return f"✅ {types.get(req_type, 'Petición')} enviada"
        return self.operation_error("enviar la peticion")

    # ── Proyectos ───────────────────────────────────────────

    async def find_project(self, term: str, customer_id: str = "2396") -> dict | None:
        result = await self._request(PROJECTS_URL, {"term": term, "customer": customer_id})
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    async def list_projects(self, customer_id: str = "2396") -> str:
        result = await self._request(PROJECTS_URL, {"term": "", "customer": customer_id})
        if not result or not isinstance(result, list):
            return self.operation_error("cargar los proyectos")

        lines = ["📁 *Proyectos*\n"]
        for p in result[:15]:
            name = self._esc(p.get("label", p.get("value", "?")))
            pid = p.get("id", "?")
            lines.append(f"• {name} (id: {pid})")
        return "\n".join(lines)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
