"""Yarig.ai integration — fetch daily tasks and objectives."""

import logging
import aiohttp
from src.config import YARIG_EMAIL, YARIG_PASSWORD

logger = logging.getLogger(__name__)

YARIG_BASE = "https://yarig.ai"
LOGIN_URL = f"{YARIG_BASE}/registration/login"
TASKS_URL = f"{YARIG_BASE}/tasks/json_get_current_day_tasks_and_journey_info"
SCORE_URL = f"{YARIG_BASE}/score/json_user_score"


class YarigClient:
    """Async client for Yarig.ai with session-based auth."""

    def __init__(self, email: str = YARIG_EMAIL, password: str = YARIG_PASSWORD):
        self.email = email
        self.password = password
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            # yarig.ai has an incomplete SSL certificate chain
            connector = aiohttp.TCPConnector(ssl=False)
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
            self._logged_in = False

    async def login(self) -> bool:
        """Login to Yarig.ai with email/password."""
        if not self.email or not self.password:
            logger.warning("Yarig credentials not configured")
            return False

        await self._ensure_session()

        try:
            # Get login page first to establish session cookie
            async with self._session.get(LOGIN_URL) as r:
                pass

            # POST login
            async with self._session.post(
                LOGIN_URL,
                data={"email": self.email, "password": self.password, "submit": "Entrar"},
                allow_redirects=True,
            ) as resp:
                if resp.status == 200 and "/tasks" in str(resp.url):
                    self._logged_in = True
                    logger.info("Yarig login successful")
                    return True
                logger.warning(f"Yarig login failed: status={resp.status}, url={resp.url}")
                return False
        except Exception as e:
            logger.warning(f"Yarig login error: {e}")
            return False

    async def _request(self, url: str) -> dict | None:
        """Make an authenticated request, re-logging in if needed."""
        await self._ensure_session()

        if not self._logged_in:
            if not await self.login():
                return None

        try:
            async with self._session.post(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data is not None:
                        return data

                # Session expired — try re-login once
                self._logged_in = False
                if await self.login():
                    async with self._session.post(url) as retry:
                        if retry.status == 200:
                            return await retry.json(content_type=None)

                logger.warning(f"Yarig request failed: {url} status={resp.status}")
                return None
        except Exception as e:
            logger.warning(f"Yarig request error: {e}")
            return None

    @staticmethod
    def _esc(text: str) -> str:
        """Escape Markdown special chars for Telegram."""
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, f"\\{ch}")
        return text

    async def get_today_tasks(self) -> list[dict]:
        """Get current day tasks for the logged-in user."""
        data = await self._request(TASKS_URL)
        if not data:
            return []
        return data.get("tasks", [])

    async def get_today_summary(self) -> str:
        """Get a formatted summary of today's tasks."""
        data = await self._request(TASKS_URL)
        if not data:
            return "No se pudo conectar con Yarig.ai"

        tasks = data.get("tasks", [])
        clocking = data.get("clocking", [])

        if not tasks and not clocking:
            return "Sin tareas para hoy en Yarig.ai"

        lines = ["📋 *Tareas del día (Yarig.ai)*\n"]

        for i, task in enumerate(tasks, 1):
            desc = self._esc(task.get("description", "").strip())
            project = self._esc(task.get("project", ""))
            finished = task.get("finished", "0")
            start_time = task.get("start_time")
            end_time = task.get("end_time")

            if finished == "1":
                status = "✅"
            elif start_time and not end_time:
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

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
