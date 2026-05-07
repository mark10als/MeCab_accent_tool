# coding=utf-8
"""
MeCab CSV エクスポート & コンパイルモジュール

AccentDB の内容を MeCab ユーザー辞書 CSV に変換し、
mecab-dict-index でコンパイルして .dic ファイルを生成する。
"""

import os
import subprocess
from typing import Iterator, Dict, Optional

from .accent_db import AccentDB

# ── MeCab 設定 ────────────────────────────────────────────────

MECAB_BIN_DIR    = r"C:\Program Files\MeCab\bin"
MECAB_DIC_DIR    = r"C:\Program Files\MeCab\dic\ipadic"
MECAB_DICT_INDEX = os.path.join(MECAB_BIN_DIR, "mecab-dict-index.exe")


# ══════════════════════════════════════════════════════════════
#  CSV 行生成
# ══════════════════════════════════════════════════════════════

def _entry_to_csv_row(entry: Dict) -> str:
    """
    DBエントリを MeCab CSV 行（14フィールド）に変換する。

    フォーマット（ipadic 拡張、14フィールド）:
      表層形, 左ID, 右ID, コスト,
      品詞, 品詞細分類1, 品詞細分類2, 品詞細分類3,
      活用型, 活用形, 原形, 読み（カタカナ）, 発音（カタカナ）,
      アクセント型   ← 14番目（独自拡張）
    """
    surface      = entry.get("surface", "")
    reading_kata = entry.get("reading_kata", "")
    pos          = entry.get("pos", "名詞")
    pos2         = entry.get("pos2", "*")
    left_id      = entry.get("left_id",  1285)
    right_id     = entry.get("right_id", 1285)
    cost         = entry.get("cost",     5000)
    accent_type  = entry.get("accent_type", 0)

    # 品詞細分類2・3はデフォルト *
    fields = [
        surface,        # 0: 表層形
        str(left_id),   # 1: 左文脈ID
        str(right_id),  # 2: 右文脈ID
        str(cost),      # 3: コスト
        pos,            # 4: 品詞
        pos2,           # 5: 品詞細分類1
        "*",            # 6: 品詞細分類2
        "*",            # 7: 品詞細分類3
        "*",            # 8: 活用型
        "*",            # 9: 活用形
        surface,        # 10: 原形
        reading_kata,   # 11: 読み（カタカナ）
        reading_kata,   # 12: 発音（カタカナ）
        str(accent_type),  # 13: アクセント型（独自拡張）
    ]
    return ",".join(fields)


# ══════════════════════════════════════════════════════════════
#  CsvExporter クラス
# ══════════════════════════════════════════════════════════════

class CsvExporter:
    """
    AccentDB → CSV → .dic の変換を担当するクラス。
    """

    def __init__(
        self,
        db: AccentDB,
        output_dir: str,
        mecab_dict_index: str = MECAB_DICT_INDEX,
        mecab_dic_dir: str    = MECAB_DIC_DIR,
    ):
        self.db               = db
        self.output_dir       = output_dir
        self.mecab_dict_index = mecab_dict_index
        self.mecab_dic_dir    = mecab_dic_dir
        os.makedirs(output_dir, exist_ok=True)

    # ── CSV エクスポート ────────────────────────────────────

    def export_csv(
        self,
        csv_filename: str = "mecab_accent.csv",
        reviewed_only: bool = False,
        pos_filter: Optional[str] = None,
        cost_override: Optional[int] = None,
        manual_cost: Optional[int] = None,
    ) -> Iterator[Dict]:
        """
        DB からエントリを読み出して CSV ファイルに書き出す。

        Args:
            csv_filename:   出力ファイル名
            reviewed_only:  True=確認済みエントリのみ
            pos_filter:     品詞フィルタ（例: "名詞"）
            cost_override:  全エントリのコストを上書き（None=元のコストを使用）
            manual_cost:    source="manual" のエントリのコスト（None=cost_overrideと同じ）

        Yields:
            進捗 dict: {written, current_surface}
        """
        csv_path = os.path.join(self.output_dir, csv_filename)

        written  = 0
        with open(csv_path, encoding="utf-8", mode="w", newline="\n") as f:
            for entry in self.db.iter_all(reviewed_only=reviewed_only):
                if pos_filter and entry.get("pos") != pos_filter:
                    continue
                if not entry.get("reading_kata"):
                    continue

                # コスト決定
                if entry.get("source") == "manual" and manual_cost is not None:
                    entry = dict(entry)
                    entry["cost"] = manual_cost
                elif cost_override is not None:
                    entry = dict(entry)
                    entry["cost"] = cost_override

                row = _entry_to_csv_row(entry)
                f.write(row + "\n")
                written += 1

                if written % 1000 == 0:
                    yield {"written": written, "current_surface": entry.get("surface", "")}

        yield {"written": written, "done": True, "csv_path": csv_path}

    # ── .dic コンパイル ─────────────────────────────────────

    def compile_dic(
        self,
        csv_filename: str = "mecab_accent.csv",
        dic_filename: str = "mecab_accent.dic",
    ) -> Dict:
        """
        mecab-dict-index で CSV → .dic にコンパイルする。

        Returns:
            {success: bool, dic_path: str, message: str}
        """
        csv_path = os.path.join(self.output_dir, csv_filename)
        dic_path = os.path.join(self.output_dir, dic_filename)

        # 事前チェック
        if not os.path.exists(self.mecab_dict_index):
            return {
                "success": False,
                "message": f"❌ mecab-dict-index が見つかりません:\n{self.mecab_dict_index}",
            }
        if not os.path.exists(csv_path):
            return {
                "success": False,
                "message": f"❌ CSV ファイルが見つかりません:\n{csv_path}\n先に「CSV エクスポート」を実行してください。",
            }
        if not os.path.exists(self.mecab_dic_dir):
            return {
                "success": False,
                "message": f"❌ MeCab 辞書ディレクトリが見つかりません:\n{self.mecab_dic_dir}",
            }

        cmd = [
            self.mecab_dict_index,
            "-d", self.mecab_dic_dir,
            "-u", dic_path,
            "-f", "utf-8",
            "-t", "utf-8",
            csv_path,
        ]
        print(f"[INFO] コンパイル実行: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                size = os.path.getsize(dic_path)
                return {
                    "success":  True,
                    "dic_path": dic_path,
                    "message":  (
                        f"✅ コンパイル成功！\n"
                        f"出力: {dic_path}\n"
                        f"サイズ: {size:,} バイト"
                    ),
                }
            else:
                return {
                    "success": False,
                    "message": f"❌ コンパイルエラー:\n{result.stderr or result.stdout}",
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ 実行エラー: {type(e).__name__}: {e}",
            }

    def export_and_compile(
        self,
        csv_filename: str = "mecab_accent.csv",
        dic_filename: str = "mecab_accent.dic",
        reviewed_only: bool = False,
        manual_cost: int = 4000,
    ) -> Iterator[Dict]:
        """
        CSV エクスポートからコンパイルまでを一連で実行する。

        Yields:
            進捗 dict
        """
        yield {"status": "CSV エクスポート中..."}

        written = 0
        for prog in self.export_csv(
            csv_filename=csv_filename,
            reviewed_only=reviewed_only,
            manual_cost=manual_cost,
        ):
            written = prog.get("written", written)
            yield {"status": f"CSV 書き込み中... {written:,} 件", **prog}

        yield {"status": f"CSV エクスポート完了: {written:,} 件\nコンパイル中..."}

        result = self.compile_dic(csv_filename, dic_filename)
        yield {"status": result["message"], "compile_result": result}
