# coding=utf-8
"""
SQLite ベースのアクセント辞書データベース

スキーマ:
  accent_entries テーブルに全単語のアクセント情報を格納。
  ipadic CSV 由来エントリ・ユーザー手動登録・バッチ予測結果を統合管理。
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Iterator


# ══════════════════════════════════════════════════════════════
#  スキーマ定義
# ══════════════════════════════════════════════════════════════

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS accent_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    surface      TEXT    NOT NULL,
    reading_kata TEXT    NOT NULL DEFAULT '',
    pos          TEXT    NOT NULL DEFAULT '',
    pos2         TEXT    NOT NULL DEFAULT '',
    left_id      INTEGER NOT NULL DEFAULT 0,
    right_id     INTEGER NOT NULL DEFAULT 0,
    cost         INTEGER NOT NULL DEFAULT 5000,
    accent_type  INTEGER NOT NULL DEFAULT 0,
    mora_count   INTEGER NOT NULL DEFAULT 0,
    confidence   REAL    NOT NULL DEFAULT 0.0,
    source       TEXT    NOT NULL DEFAULT 'manual',
    reviewed     INTEGER NOT NULL DEFAULT 0,
    note         TEXT    NOT NULL DEFAULT '',
    ipadic_csv   TEXT    NOT NULL DEFAULT '',
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(surface, pos, reading_kata)
);

CREATE INDEX IF NOT EXISTS idx_surface     ON accent_entries(surface);
CREATE INDEX IF NOT EXISTS idx_pos         ON accent_entries(pos);
CREATE INDEX IF NOT EXISTS idx_source      ON accent_entries(source);
CREATE INDEX IF NOT EXISTS idx_reviewed    ON accent_entries(reviewed);
CREATE INDEX IF NOT EXISTS idx_ipadic_csv  ON accent_entries(ipadic_csv);
"""


# ══════════════════════════════════════════════════════════════
#  AccentDB クラス
# ══════════════════════════════════════════════════════════════

class AccentDB:
    """
    アクセント辞書 SQLite データベース管理クラス。

    スレッドセーフ: check_same_thread=False で接続する。
    大量一括挿入時は bulk_insert() を使うこと（transaction でまとめる）。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=30,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_CREATE_SQL)
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ── 単件操作 ────────────────────────────────────────────

    def upsert(self, entry: Dict) -> bool:
        """
        エントリを追加または更新する。

        Args:
            entry: キー → surface, reading_kata, pos, pos2, left_id, right_id,
                         cost, accent_type, mora_count, confidence, source,
                         reviewed, note, ipadic_csv

        Returns:
            True=新規追加 / False=更新
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT INTO accent_entries
            (surface, reading_kata, pos, pos2, left_id, right_id, cost,
             accent_type, mora_count, confidence, source, reviewed, note,
             ipadic_csv, updated_at)
        VALUES
            (:surface, :reading_kata, :pos, :pos2, :left_id, :right_id, :cost,
             :accent_type, :mora_count, :confidence, :source, :reviewed, :note,
             :ipadic_csv, :updated_at)
        ON CONFLICT(surface, pos, reading_kata) DO UPDATE SET
            pos2        = excluded.pos2,
            left_id     = excluded.left_id,
            right_id    = excluded.right_id,
            cost        = excluded.cost,
            accent_type = excluded.accent_type,
            mora_count  = excluded.mora_count,
            confidence  = excluded.confidence,
            source      = excluded.source,
            reviewed    = excluded.reviewed,
            note        = excluded.note,
            ipadic_csv  = excluded.ipadic_csv,
            updated_at  = excluded.updated_at
        """
        row = {
            "surface":      entry.get("surface", ""),
            "reading_kata": entry.get("reading_kata", ""),
            "pos":          entry.get("pos", ""),
            "pos2":         entry.get("pos2", ""),
            "left_id":      entry.get("left_id", 0),
            "right_id":     entry.get("right_id", 0),
            "cost":         entry.get("cost", 5000),
            "accent_type":  entry.get("accent_type", 0),
            "mora_count":   entry.get("mora_count", 0),
            "confidence":   entry.get("confidence", 0.0),
            "source":       entry.get("source", "manual"),
            "reviewed":     1 if entry.get("reviewed") else 0,
            "note":         entry.get("note", ""),
            "ipadic_csv":   entry.get("ipadic_csv", ""),
            "updated_at":   now,
        }
        cur = self._conn.execute(sql, row)
        self._conn.commit()
        return cur.lastrowid > 0

    def get(self, surface: str, pos: str = "", reading_kata: str = "") -> Optional[Dict]:
        """
        表層形・品詞・読みで1件取得する。
        reading_kata が空の場合は surface + pos だけで最初の一致を返す。
        """
        if reading_kata:
            cur = self._conn.execute(
                "SELECT * FROM accent_entries WHERE surface=? AND pos=? AND reading_kata=?",
                (surface, pos, reading_kata),
            )
        elif pos:
            cur = self._conn.execute(
                "SELECT * FROM accent_entries WHERE surface=? AND pos=?",
                (surface, pos),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM accent_entries WHERE surface=? ORDER BY reviewed DESC, confidence DESC LIMIT 1",
                (surface,),
            )
        row = cur.fetchone()
        return dict(row) if row else None

    def delete(self, surface: str, pos: str = "", reading_kata: str = "") -> int:
        """削除して削除件数を返す"""
        if reading_kata and pos:
            cur = self._conn.execute(
                "DELETE FROM accent_entries WHERE surface=? AND pos=? AND reading_kata=?",
                (surface, pos, reading_kata),
            )
        elif pos:
            cur = self._conn.execute(
                "DELETE FROM accent_entries WHERE surface=? AND pos=?",
                (surface, pos),
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM accent_entries WHERE surface=?",
                (surface,),
            )
        self._conn.commit()
        return cur.rowcount

    def mark_reviewed(self, surface: str, pos: str, reading_kata: str, reviewed: bool = True):
        self._conn.execute(
            "UPDATE accent_entries SET reviewed=?, updated_at=? WHERE surface=? AND pos=? AND reading_kata=?",
            (1 if reviewed else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             surface, pos, reading_kata),
        )
        self._conn.commit()

    # ── 一括操作 ────────────────────────────────────────────

    def bulk_insert(self, rows: List[Dict], overwrite: bool = False) -> Tuple[int, int]:
        """
        大量挿入。既存エントリの扱い:
          overwrite=True  → 無条件で上書き
          overwrite=False → 既存を保持（source='manual' や reviewed=1 を優先）

        Returns:
            (inserted, skipped)
        """
        inserted = skipped = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sql_insert = """
        INSERT OR IGNORE INTO accent_entries
            (surface, reading_kata, pos, pos2, left_id, right_id, cost,
             accent_type, mora_count, confidence, source, reviewed, note,
             ipadic_csv, updated_at)
        VALUES
            (:surface, :reading_kata, :pos, :pos2, :left_id, :right_id, :cost,
             :accent_type, :mora_count, :confidence, :source, 0, :note,
             :ipadic_csv, :updated_at)
        """
        sql_update = """
        UPDATE accent_entries SET
            accent_type=:accent_type, mora_count=:mora_count,
            confidence=:confidence, source=:source, updated_at=:updated_at
        WHERE surface=:surface AND pos=:pos AND reading_kata=:reading_kata
          AND reviewed=0
        """

        chunk = []
        for row in rows:
            row["updated_at"] = now
            chunk.append(row)
            if len(chunk) >= 500:
                n, s = self._flush_bulk(chunk, sql_insert, sql_update, overwrite)
                inserted += n
                skipped  += s
                chunk = []

        if chunk:
            n, s = self._flush_bulk(chunk, sql_insert, sql_update, overwrite)
            inserted += n
            skipped  += s

        return inserted, skipped

    def _flush_bulk(self, rows, sql_insert, sql_update, overwrite):
        inserted = skipped = 0
        with self._conn:
            for row in rows:
                if overwrite:
                    cur = self._conn.execute(sql_insert, row)
                    if cur.rowcount == 0:
                        self._conn.execute(sql_update, row)
                        skipped += 1
                    else:
                        inserted += 1
                else:
                    cur = self._conn.execute(sql_insert, row)
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
        return inserted, skipped

    # ── 検索・一覧 ──────────────────────────────────────────

    def search(
        self,
        surface_q: str = "",
        pos_filter: str = "",
        source_filter: str = "",
        reviewed_filter: int = -1,
        ipadic_csv_filter: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> Tuple[List[Dict], int]:
        """
        条件検索。

        Returns:
            (rows, total_count)
        """
        conds, params = [], []

        if surface_q:
            conds.append("surface LIKE ?")
            params.append(f"%{surface_q}%")
        if pos_filter:
            conds.append("pos=?")
            params.append(pos_filter)
        if source_filter:
            conds.append("source=?")
            params.append(source_filter)
        if reviewed_filter >= 0:
            conds.append("reviewed=?")
            params.append(reviewed_filter)
        if ipadic_csv_filter:
            conds.append("ipadic_csv=?")
            params.append(ipadic_csv_filter)

        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        total = self._conn.execute(
            f"SELECT COUNT(*) FROM accent_entries {where}", params
        ).fetchone()[0]

        rows = self._conn.execute(
            f"SELECT * FROM accent_entries {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return [dict(r) for r in rows], total

    def iter_all(self, reviewed_only: bool = False) -> Iterator[Dict]:
        """全エントリをイテレートする（メモリ効率重視）"""
        where = "WHERE reviewed=1" if reviewed_only else ""
        cur = self._conn.execute(
            f"SELECT * FROM accent_entries {where} ORDER BY surface"
        )
        for row in cur:
            yield dict(row)

    # ── 統計 ────────────────────────────────────────────────

    def stats(self) -> Dict:
        """統計情報を返す"""
        cur = self._conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(reviewed) AS reviewed,
                COUNT(DISTINCT source) AS sources,
                COUNT(DISTINCT pos) AS pos_count,
                COUNT(DISTINCT ipadic_csv) AS csv_count
            FROM accent_entries
        """)
        row = dict(cur.fetchone())

        src_rows = self._conn.execute(
            "SELECT source, COUNT(*) AS cnt FROM accent_entries GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        row["by_source"] = {r["source"]: r["cnt"] for r in src_rows}

        pos_rows = self._conn.execute(
            "SELECT pos, COUNT(*) AS cnt FROM accent_entries GROUP BY pos ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        row["by_pos"] = {r["pos"]: r["cnt"] for r in pos_rows}

        return row

    def count_by_csv(self) -> Dict[str, int]:
        """CSVファイル別のエントリ数"""
        rows = self._conn.execute(
            "SELECT ipadic_csv, COUNT(*) AS cnt FROM accent_entries GROUP BY ipadic_csv"
        ).fetchall()
        return {r["ipadic_csv"]: r["cnt"] for r in rows}

    def has_entry_for_csv(self, ipadic_csv: str) -> bool:
        """指定 CSV ファイルのエントリが1件以上あるか"""
        row = self._conn.execute(
            "SELECT 1 FROM accent_entries WHERE ipadic_csv=? LIMIT 1",
            (ipadic_csv,)
        ).fetchone()
        return row is not None
