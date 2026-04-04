"""Yarig.ai integration — full platform access via API."""

import logging
import time
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


class YarigClient:
    """Async client for Yarig.ai with full platform access."""

    def __init__(self, email: str = YARIG_EMAIL, password: str = YARIG_PASSWORD):
        self.email = email
        self.password = password
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
            self._logged_in = False

    async def login(self) -> bool:
        if not self.email or not self.password:
            logger.warning("Yarig credentials not configured")
            return False
        await self._ensure_session()
        try:
            await self._session.get(LOGIN_URL)
            async with self._session.post(
                LOGIN_URL,
                data={"email": self.email, "password": self.password, "submit": "Entrar"},
                allow_redirects=True,
            ) as resp:
                if resp.status == 200 and "/tasks" in str(resp.url):
                    self._logged_in = True
                    logger.info("Yarig login successful")
                    return True
                logger.warning(f"Yarig login failed: url={resp.url}")
                return False
        except Exception as e:
            logger.warning(f"Yarig login error: {e}")
            return False

    async def _request(self, url: str, data: dict | None = None, method: str = "POST") -> dict | list | int | None:
        await self._ensure_session()
        if not self._logged_in:
            if not await self.login():
                return None
        try:
            kw = {"data": data} if data else {}
            async with self._session.request(method, url, **kw) as resp:
                if resp.status == 200:
                    result = await resp.json(content_type=None)
                    return result
                # Session expired
                self._logged_in = False
                if await self.login():
                    async with self._session.request(method, url, **kw) as retry:
                        if retry.status == 200:
                            return await retry.json(content_type=None)
                logger.warning(f"Yarig request failed: {url} status={resp.status}")
                return None
        except Exception as e:
            logger.warning(f"Yarig request error: {e}")
            return None

    @staticmethod
    def _esc(text: str) -> str:
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, f"\\{ch}")
        return text

    # ── Tareas del día ──────────────────────────────────────

    async def get_today_data(self) -> dict | None:
        return await self._request(TASKS_URL)

    async def get_today_summary(self) -> str:
        data = await self.get_today_data()
        if not data:
            return "No se pudo conectar con Yarig.ai"

        tasks = data.get("tasks", [])
        clocking = data.get("clocking", [])

        if not tasks and not clocking:
            return "Sin tareas ni jornada para hoy en Yarig.ai"

        lines = ["📋 *Tareas del día (Yarig.ai)*\n"]

        for i, task in enumerate(tasks, 1):
            desc = self._esc(task.get("description", "").strip())
            project = self._esc(task.get("project", ""))
            finished = task.get("finished", "0")
            start = task.get("start_time")
            end = task.get("end_time")

            if finished == "1":
                status = "✅"
            elif start and not end:
                status = "▶️"
            else:
                status = "⏳"

            line = f"{i}. {status} {desc}"
            if project:
                line += f" — _{project}_"
            lines.append(line)

        if not tasks:
            lines.append("(sin tareas registradas)")

        if clocking:
            entry = clocking[0]
            name = self._esc(entry.get("name", ""))
            dt = entry.get("datetime", "?")
            lines.append(f"\n🕐 Jornada de *{name}* iniciada: {dt}")

        return "\n".join(lines)

    # ── Fichar ──────────────────────────────────────────────

    async def fichar_entrada(self) -> str:
        result = await self._request(CLOCKING_URL, {"type": 0, "todo": ""})
        if result:
            return "✅ Jornada iniciada"
        return "⚠️ No se pudo fichar entrada (¿ya estás fichado?)"

    async def fichar_salida(self, todo: str = "") -> str:
        result = await self._request(CLOCKING_URL, {"type": 1, "todo": todo})
        if result:
            return "✅ Jornada finalizada"
        return "⚠️ No se pudo fichar salida"

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
        return "⚠️ No se pudo añadir la tarea"

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

        tasks = data["tasks"]
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
        return "⚠️ No se pudo iniciar la tarea"

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
        return "⚠️ No se pudo pausar la tarea"

    async def finalizar_tarea(self, task_index: int | None = None) -> str:
        """Finish/complete a task (mark as done)."""
        data = await self.get_today_data()
        if not data or not data.get("tasks"):
            return "⚠️ No hay tareas para hoy"

        tasks = data["tasks"]

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
        return "⚠️ No se pudo finalizar la tarea"

    # ── Puntuación ──────────────────────────────────────────

    async def get_score(self) -> str:
        result = await self._request(SCORE_URL)
        if result is not None:
            score = int(result) if isinstance(result, (int, str)) else 0
            emoji = "🏆" if score > 0 else "📉" if score < 0 else "➖"
            return f"{emoji} Tu puntuación en Yarig: *{score}* puntos"
        return "⚠️ No se pudo obtener la puntuación"

    # ── Equipo ──────────────────────────────────────────────

    async def get_team(self) -> str:
        result = await self._request(USERS_URL, {"term": ""})
        if not result or not result.get("mates"):
            return "⚠️ No se pudo obtener el equipo"

        mates = result["mates"]
        lines = [f"👥 *Equipo Yarig.ai* ({len(mates)} miembros)\n"]
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
                return "⚠️ No se pudo conectar con Yarig.ai"

        try:
            async with self._session.get(f"{YARIG_BASE}/tasks/history") as resp:
                if resp.status != 200:
                    return "⚠️ No se pudo obtener el historial"
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
            logger.warning(f"History error: {e}")
            return "⚠️ Error al obtener el historial"

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
        return "⚠️ No se pudo enviar la petición"

    # ── Proyectos ───────────────────────────────────────────

    async def find_project(self, term: str, customer_id: str = "2396") -> dict | None:
        result = await self._request(PROJECTS_URL, {"term": term, "customer": customer_id})
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    async def list_projects(self, customer_id: str = "2396") -> str:
        result = await self._request(PROJECTS_URL, {"term": "", "customer": customer_id})
        if not result or not isinstance(result, list):
            return "⚠️ No se encontraron proyectos"

        lines = ["📁 *Proyectos*\n"]
        for p in result[:15]:
            name = self._esc(p.get("label", p.get("value", "?")))
            pid = p.get("id", "?")
            lines.append(f"• {name} (id: {pid})")
        return "\n".join(lines)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
