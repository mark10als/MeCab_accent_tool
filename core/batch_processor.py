# coding=utf-8
"""
ipadic CSV 一括処理モジュール

MeCab の ipadic ソース CSV を読み込み、pyopenjtalk でアクセントを予測して
SQLite データベースに一括登録する。
"""

import csv
import os
import re
from typing import List, Dict, Tuple, Optional, Callable, Iterator

from .accent_db import AccentDB
from .accent_predictor import (
    AccentPredictor,
    katakana_to_hiragana,
    count_morae,
    OPENJTALK_AVAILABLE,
)

# ══════════════════════════════════════════════════════════════
#  ipadic CSV ファイル定義
# ══════════════════════════════════════════════════════════════

# ipadic CSV の全ファイルリスト（処理対象）
IPADIC_CSV_FILES = [
    "Noun.csv",          # 名詞（一般）
    "Noun.proper.csv",   # 名詞（固有名詞）
    "Noun.name.csv",     # 名詞（人名）
    "Noun.place.csv",    # 名詞（地名）
    "Noun.org.csv",      # 名詞（組織）
    "Noun.verbal.csv",   # 名詞（サ変接続）
    "Noun.adjv.csv",     # 名詞（形容動詞語幹）
    "Noun.adverbal.csv", # 名詞（副詞可能）
    "Noun.others.csv",   # 名詞（その他）
    "Noun.demonst.csv",  # 名詞（代名詞）
    "Noun.nai.csv",      # 名詞（ナイ形容詞語幹）
    "Noun.number.csv",   # 名詞（数）
    "Verb.csv",          # 動詞
    "Adj.csv",           # 形容詞
    "Adverb.csv",        # 副詞
    "Adnominal.csv",     # 連体詞
    "Conjunction.csv",   # 接続詞
    "Interjection.csv",  # 感動詞
    "Auxil.csv",         # 助動詞
    "Postp.csv",         # 助詞
    "Postp-col.csv",     # 助詞（格助詞）
    "Prefix.csv",        # 接頭詞
    "Suffix.csv",        # 接尾詞
    "Symbol.csv",        # 記号
    "Others.csv",        # その他
    "Filler.csv",        # フィラー
]

# アクセント解析の優先度（品詞別）
# 高い数値 = 優先度高（TTS で重要度が高い品詞）
POS_PRIORITY = {
    "名詞":   10,
    "動詞":    9,
    "形容詞":  8,
    "副詞":    7,
    "接続詞":  6,
    "感動詞":  5,
    "助詞":    4,
    "助動詞":  3,
    "接頭詞":  2,
    "接尾詞":  2,
    "記号":    1,
}


# ══════════════════════════════════════════════════════════════
#  CSV 解析
# ══════════════════════════════════════════════════════════════

def _read_ipadic_csv(csv_path: str) -> Iterator[Dict]:
    """
    ipadic CSV ファイルを1行ずつパースしてイテレートする。

    ipadic CSV フォーマット（13フィールド）:
      0: 表層形
      1: 左文脈ID
      2: 右文脈ID
      3: コスト
      4: 品詞
      5: 品詞細分類1
      6: 品詞細分類2
      7: 品詞細分類3
      8: 活用型
      9: 活用形
     10: 原形
     11: 読み（カタカナ）
     12: 発音（カタカナ）

    Yields:
        dict with keys: surface, left_id, right_id, cost, pos, pos2, pos3, pos4,
                        conj_type, conj_form, base_form, reading_kata, pronounce
    """
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 13:
                continue
            try:
                yield {
                    "surface":      row[0],
                    "left_id":      int(row[1]) if row[1].lstrip("-").isdigit() else 0,
                    "right_id":     int(row[2]) if row[2].lstrip("-").isdigit() else 0,
                    "cost":         int(row[3]) if row[3].lstrip("-").isdigit() else 5000,
                    "pos":          row[4],
                    "pos2":         row[5],
                    "pos3":         row[6],
                    "pos4":         row[7],
                    "conj_type":    row[8],
                    "conj_form":    row[9],
                    "base_form":    row[10],
                    "reading_kata": row[11] if row[11] not in ("*", "") else "",
                    "pronounce":    row[12] if row[12] not in ("*", "") else "",
                }
            except (ValueError, IndexError):
                continue


def _should_skip(entry: Dict) -> bool:
    """
    アクセント解析をスキップすべきエントリか判定する。

    スキップ条件:
      - 読みがない（記号・数字など）
      - 読みが表層形と同じでカタカナのみ（固有名詞はスキップしない）
      - 表層形が空
    """
    surface = entry.get("surface", "").strip()
    reading = entry.get("reading_kata", "").strip()

    if not surface or not reading:
        return True

    # 記号・数字のみ
    if re.fullmatch(r"[a-zA-Z0-9\s\-_.,!?]+", surface):
        return True

    return False


# ══════════════════════════════════════════════════════════════
#  BatchProcessor クラス
# ══════════════════════════════════════════════════════════════

class BatchProcessor:
    """
    ipadic CSV ファイルのバッチ処理クラス。

    使い方:
        bp = BatchProcessor(db, ipadic_dir)
        for status in bp.process_csv_file("Noun.csv", overwrite=False):
            print(status)   # 進捗メッセージ
    """

    def __init__(self, db: AccentDB, ipadic_dir: str):
        """
        Args:
            db:         AccentDB インスタンス
            ipadic_dir: ipadic ソース CSV のディレクトリ
                        （例: C:\\Program Files\\MeCab\\dic\\ipadic）
        """
        self.db         = db
        self.ipadic_dir = ipadic_dir
        self.predictor  = AccentPredictor()

    def available_csv_files(self) -> List[Dict]:
        """
        処理可能な CSV ファイルのリストを返す。

        Returns:
            list of {filename, path, line_count, processed}
            processed: DB にエントリが存在するか
        """
        result = []
        processed_counts = self.db.count_by_csv()

        for fname in IPADIC_CSV_FILES:
            path = os.path.join(self.ipadic_dir, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                line_count = 0
            result.append({
                "filename":   fname,
                "path":       path,
                "line_count": line_count,
                "processed":  processed_counts.get(fname, 0),
            })
        return result

    def process_csv_file(
        self,
        csv_filename: str,
        overwrite: bool = False,
        pos_filter: Optional[List[str]] = None,
        progress_fn: Optional[Callable[[int, int, str], None]] = None,
    ) -> Iterator[Dict]:
        """
        1つの CSV ファイルを処理する。

        Args:
            csv_filename: ファイル名（例: "Noun.csv"）
            overwrite:    True=既存エントリを上書き
            pos_filter:   処理する品詞リスト（None=全品詞）
            progress_fn:  fn(processed, total, message) 進捗コールバック

        Yields:
            進捗情報 dict: {processed, total, inserted, skipped, current}
        """
        csv_path = os.path.join(self.ipadic_dir, csv_filename)
        if not os.path.exists(csv_path):
            yield {"error": f"ファイルが見つかりません: {csv_path}"}
            return

        # 全エントリ読み込み（件数カウント用）
        all_entries = list(_read_ipadic_csv(csv_path))
        total = len(all_entries)

        inserted = skipped = errors = 0
        batch: List[Dict] = []

        for i, ipadic_entry in enumerate(all_entries):
            if _should_skip(ipadic_entry):
                skipped += 1
                continue

            pos = ipadic_entry["pos"]
            if pos_filter and pos not in pos_filter:
                skipped += 1
                continue

            reading_kata = ipadic_entry["reading_kata"]
            reading_hira = katakana_to_hiragana(reading_kata)

            # アクセント予測
            try:
                accent_type, mora_count, confidence, source = self.predictor.predict(
                    reading_hira, ipadic_entry["surface"]
                )
            except Exception as e:
                errors += 1
                accent_type, mora_count, confidence, source = 0, count_morae(reading_hira), 0.0, "error"

            db_entry = {
                "surface":      ipadic_entry["surface"],
                "reading_kata": reading_kata,
                "pos":          pos,
                "pos2":         ipadic_entry["pos2"],
                "left_id":      ipadic_entry["left_id"],
                "right_id":     ipadic_entry["right_id"],
                "cost":         ipadic_entry["cost"],
                "accent_type":  accent_type,
                "mora_count":   mora_count,
                "confidence":   confidence,
                "source":       source,
                "reviewed":     0,
                "note":         "",
                "ipadic_csv":   csv_filename,
            }
            batch.append(db_entry)

            # 500件ごとに一括挿入
            if len(batch) >= 500:
                n, s = self.db.bulk_insert(batch, overwrite=overwrite)
                inserted += n
                skipped  += s
                batch = []

            if i % 200 == 0 or i == total - 1:
                yield {
                    "processed": i + 1,
                    "total":     total,
                    "inserted":  inserted,
                    "skipped":   skipped,
                    "errors":    errors,
                    "current":   ipadic_entry["surface"],
                }

        # 残りを処理
        if batch:
            n, s = self.db.bulk_insert(batch, overwrite=overwrite)
            inserted += n
            skipped  += s

        yield {
            "processed": total,
            "total":     total,
            "inserted":  inserted,
            "skipped":   skipped,
            "errors":    errors,
            "done":      True,
        }

    def process_multiple(
        self,
        csv_filenames: List[str],
        overwrite: bool = False,
        pos_filter: Optional[List[str]] = None,
    ) -> Iterator[Dict]:
        """
        複数の CSV ファイルをまとめて処理する。

        Yields:
            進捗情報 dict（各ファイルの処理状況を含む）
        """
        total_files   = len(csv_filenames)
        total_inserted = 0
        total_skipped  = 0

        for file_idx, csv_filename in enumerate(csv_filenames):
            yield {
                "file_idx":    file_idx,
                "file_total":  total_files,
                "current_file": csv_filename,
                "status":      f"処理開始: {csv_filename} ({file_idx+1}/{total_files})",
            }

            for progress in self.process_csv_file(csv_filename, overwrite, pos_filter):
                if "error" in progress:
                    yield {"error": progress["error"], "file": csv_filename}
                    break
                total_inserted += progress.get("inserted", 0) - total_inserted
                total_skipped  += progress.get("skipped",  0) - total_skipped
                yield {
                    "file_idx":    file_idx,
                    "file_total":  total_files,
                    "current_file": csv_filename,
                    **progress,
                }

        yield {
            "all_done":     True,
            "total_files":  total_files,
            "total_inserted": total_inserted,
            "total_skipped":  total_skipped,
        }

    def import_from_user_dict_json(
        self,
        json_path: str,
        overwrite: bool = True,
    ) -> Tuple[int, int, str]:
        """
        user_dict.json からインポートする。

        Returns:
            (inserted, skipped, message)
        """
        import json
        from .accent_predictor import accent_type_name

        if not os.path.exists(json_path):
            return 0, 0, f"❌ ファイルが見つかりません: {json_path}"

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return 0, 0, f"❌ 読み込みエラー: {e}"

        batch = []
        for surface, info in data.items():
            if surface.startswith("_"):
                continue
            reading_hira = info.get("reading", "").strip()
            if not reading_hira:
                continue
            reading_kata = "".join(
                chr(ord(ch) + 0x60) if 0x3041 <= ord(ch) <= 0x3096 else ch
                for ch in reading_hira
            )
            accent_type  = int(info.get("accent_type", 0))
            mora_count   = count_morae(reading_hira)

            batch.append({
                "surface":      surface,
                "reading_kata": reading_kata,
                "pos":          "名詞",
                "pos2":         "固有名詞",
                "left_id":      1288,
                "right_id":     1288,
                "cost":         4000,  # 標準より低コスト（優先度高）
                "accent_type":  accent_type,
                "mora_count":   mora_count,
                "confidence":   1.0,
                "source":       "manual",
                "reviewed":     1,
                "note":         info.get("note", ""),
                "ipadic_csv":   "user_dict.json",
            })

        inserted, skipped = self.db.bulk_insert(batch, overwrite=overwrite)
        return inserted, skipped, f"✅ {inserted} 件インポート（スキップ: {skipped} 件）"
