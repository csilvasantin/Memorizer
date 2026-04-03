import aiosqlite
import json
from datetime import datetime
from pathlib import Path
from src.config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER UNIQUE,
    chat_id INTEGER,
    author TEXT,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    source TEXT DEFAULT 'unknown',
    category TEXT DEFAULT 'otro',
    summary TEXT,
    entities TEXT,
    urls TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS boosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER REFERENCES memories(id),
    forwarded_chat_id INTEGER,
    forwarded_message_id INTEGER,
    rating INTEGER DEFAULT 0,
    boosted INTEGER DEFAULT 0,
    boosted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, summary, entities, author, source, category,
    content='memories',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, summary, entities, author, source, category)
    VALUES (new.id, new.content, new.summary, new.entities, new.author, new.source, new.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, entities, author, source, category)
    VALUES ('delete', old.id, old.content, old.summary, old.entities, old.author, old.source, old.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, entities, author, source, category)
    VALUES ('delete', old.id, old.content, old.summary, old.entities, old.author, old.source, old.category);
    INSERT INTO memories_fts(rowid, content, summary, entities, author, source, category)
    VALUES (new.id, new.content, new.summary, new.entities, new.author, new.source, new.category);
END;
"""


class MemoryStorage:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def save_memory(
        self,
        telegram_message_id: int,
        chat_id: int,
        author: str,
        content: str,
        content_type: str = "text",
        source: str = "unknown",
        category: str = "otro",
        summary: str | None = None,
        entities: list | None = None,
        urls: list | None = None,
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT OR IGNORE INTO memories
                   (telegram_message_id, chat_id, author, content, content_type,
                    source, category, summary, entities, urls, processed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    telegram_message_id,
                    chat_id,
                    author,
                    content,
                    content_type,
                    source,
                    category,
                    summary,
                    json.dumps(entities or [], ensure_ascii=False),
                    json.dumps(urls or [], ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            await db.commit()
            return cursor.lastrowid

    async def save_memory_get_id(self, telegram_message_id: int, chat_id: int) -> int | None:
        """Get the ID of a memory by its telegram_message_id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM memories WHERE telegram_message_id = ? AND chat_id = ?",
                (telegram_message_id, chat_id),
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT m.*, rank
                   FROM memories_fts fts
                   JOIN memories m ON m.id = fts.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_recent(self, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_by_category(self, category: str, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_by_date_range(self, start: str, end: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM memories WHERE created_at BETWEEN ? AND ? ORDER BY created_at DESC",
                (start, end),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_boost(
        self,
        memory_id: int,
        forwarded_chat_id: int,
        forwarded_message_id: int,
        rating: int,
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO boosts (memory_id, forwarded_chat_id, forwarded_message_id, rating)
                   VALUES (?, ?, ?, ?)""",
                (memory_id, forwarded_chat_id, forwarded_message_id, rating),
            )
            await db.commit()
            return cursor.lastrowid

    async def apply_boost(self, forwarded_chat_id: int, forwarded_message_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT b.*, m.content, m.summary, m.category, m.author
                   FROM boosts b JOIN memories m ON m.id = b.memory_id
                   WHERE b.forwarded_chat_id = ? AND b.forwarded_message_id = ?""",
                (forwarded_chat_id, forwarded_message_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            row = dict(row)
            if row["boosted"]:
                return row  # already boosted
            await db.execute(
                "UPDATE boosts SET boosted = 1, boosted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), row["id"]),
            )
            await db.commit()
            row["boosted"] = 1
            return row

    async def get_top(self, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT m.*, b.rating, b.boosted, b.boosted_at
                   FROM boosts b JOIN memories m ON m.id = b.memory_id
                   WHERE b.boosted = 1
                   ORDER BY b.rating DESC, b.boosted_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_ranking(self, limit: int = 15) -> list[dict]:
        """Get all rated content ordered by rating (boosted first, then by rating)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT m.*, b.rating, b.boosted, b.boosted_at
                   FROM boosts b JOIN memories m ON m.id = b.memory_id
                   ORDER BY b.boosted DESC, b.rating DESC, b.created_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_stats(self) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            total = await db.execute_fetchall("SELECT COUNT(*) FROM memories")
            by_cat = await db.execute_fetchall(
                "SELECT category, COUNT(*) as count FROM memories GROUP BY category ORDER BY count DESC"
            )
            by_source = await db.execute_fetchall(
                "SELECT source, COUNT(*) as count FROM memories GROUP BY source ORDER BY count DESC"
            )
            return {
                "total": total[0][0],
                "by_category": {row[0]: row[1] for row in by_cat},
                "by_source": {row[0]: row[1] for row in by_source},
            }
