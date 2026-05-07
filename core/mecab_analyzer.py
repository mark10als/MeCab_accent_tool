# coding=utf-8
"""
MeCab アクセント解析モジュール

MeCab でテキストを形態素解析し、accent_db から各形態素のアクセント情報を
取得してアクセント記号付きひらがな文字列を返す。
"""

import os
import sys
from typing import List, Dict, Optional, Tuple

from .accent_db import AccentDB
from .accent_predictor import (
    predict_from_reading,
    katakana_to_hiragana,
    mark_accent,
    count_morae,
    split_morae,
    OPENJTALK_AVAILABLE,
)

# ── MeCab 設定 ────────────────────────────────────────────────

MECAB_BIN_DIR = r"C:\Program Files\MeCab\bin"
MECAB_DIC_DIR = r"C:\Program Files\MeCab\dic\ipadic"

if sys.platform == "win32" and os.path.exists(MECAB_BIN_DIR):
    cur = os.environ.get("PATH", "")
    if MECAB_BIN_DIR not in cur:
        os.environ["PATH"] = MECAB_BIN_DIR + os.pathsep + cur

try:
    import MeCab
    MECAB_AVAILABLE = True
except ImportError:
    MeCab = None
    MECAB_AVAILABLE = False


# ══════════════════════════════════════════════════════════════
#  MeCabAnalyzer クラス
# ══════════════════════════════════════════════════════════════

class MeCabAnalyzer:
    """
    MeCab + AccentDB によるアクセント解析。

    1. MeCab でテキストを形態素解析
    2. 各形態素を AccentDB で検索
    3. DB にあればそのアクセント情報を使用
    4. DB にない場合は pyopenjtalk で予測（フォールバック）

    use_compiled_dic=True の場合、コンパイル済み .dic ファイルも
    MeCab に読み込ませる（DB 検索と同等の効果、速度向上）。
    """

    def __init__(
        self,
        db: Optional[AccentDB] = None,
        compiled_dic_path: Optional[str] = None,
    ):
        """
        Args:
            db:                AccentDB インスタンス（None の場合は pyopenjtalk のみ）
            compiled_dic_path: コンパイル済み .dic ファイルのパス
        """
        self.db               = db
        self.compiled_dic     = compiled_dic_path
        self._tagger          = None
        self._tagger_with_dic = None

    def _get_tagger(self, use_compiled: bool = False) -> Optional["MeCab.Tagger"]:
        """MeCab Tagger を（キャッシュして）返す"""
        if not MECAB_AVAILABLE:
            return None

        if use_compiled and self.compiled_dic and os.path.exists(self.compiled_dic):
            if self._tagger_with_dic is None:
                try:
                    # -u オプションでユーザー辞書（コンパイル済み .dic）を追加
                    # NOTE: Windows で "Program Files" のスペース問題を避けるため
                    #       引数なしで初期化してからユーザー辞書のみ指定
                    args = f'-u "{self.compiled_dic}"'
                    self._tagger_with_dic = MeCab.Tagger(args)
                except Exception:
                    try:
                        self._tagger_with_dic = MeCab.Tagger()
                    except Exception as e:
                        print(f"[ERROR] MeCab Tagger 初期化失敗: {e}")
            return self._tagger_with_dic
        else:
            if self._tagger is None:
                try:
                    # 引数なし = システムデフォルト辞書を使用（Windows の "Program Files" パス問題を回避）
                    self._tagger = MeCab.Tagger()
                except Exception as e:
                    print(f"[ERROR] MeCab Tagger 初期化失敗: {e}")
            return self._tagger

    def parse_morphemes(self, text: str) -> List[Dict]:
        """
        MeCab でテキストを解析して形態素リストを返す。

        Returns:
            list of {surface, reading_kata, reading_hira, pos, pos2, left_id, right_id, cost}
        """
        tagger = self._get_tagger(use_compiled=False)
        if not tagger:
            return []

        node   = tagger.parseToNode(text)
        result = []

        while node:
            surface = node.surface
            if not surface:
                node = node.next
                continue
            feats = node.feature.split(",")
            pos   = feats[0] if feats else "?"
            if pos == "BOS/EOS":
                node = node.next
                continue

            pos2         = feats[1] if len(feats) > 1 else "*"
            reading_kata = feats[7] if len(feats) >= 8 and feats[7] not in ("*", "") else ""
            reading_hira = katakana_to_hiragana(reading_kata) if reading_kata else ""

            result.append({
                "surface":      surface,
                "reading_kata": reading_kata,
                "reading_hira": reading_hira,
                "pos":          pos,
                "pos2":         pos2,
            })
            node = node.next

        return result

    def get_accent_for_morpheme(
        self,
        surface: str,
        reading_kata: str,
        pos: str,
        reading_hira: str = "",
    ) -> Tuple[int, int, str, str]:
        """
        1つの形態素のアクセント情報を取得する。

        Returns:
            (accent_type, mora_count, marked_kana, source)
            source: "db_reviewed" / "db_predicted" / "pyopenjtalk" / "default"
        """
        if not reading_hira:
            reading_hira = katakana_to_hiragana(reading_kata)
        mora_count = count_morae(reading_hira) if reading_hira else 0

        # ① AccentDB 検索
        if self.db is not None:
            entry = self.db.get(surface, pos, reading_kata)
            if entry is None and pos:
                # POS が一致しない場合も試みる
                entry = self.db.get(surface)
            if entry:
                at     = entry["accent_type"]
                mc     = entry.get("mora_count", mora_count)
                marked = mark_accent(reading_hira, at) if reading_hira else surface
                src    = "db_reviewed" if entry["reviewed"] else "db_predicted"
                return at, mc, marked, src

        # ② pyopenjtalk 予測（フォールバック）
        if OPENJTALK_AVAILABLE and reading_hira:
            try:
                at, mc, conf, src = predict_from_reading(reading_hira, surface)
                marked = mark_accent(reading_hira, at)
                return at, mc, marked, src
            except Exception:
                pass

        # ③ デフォルト（平板型）
        marked = reading_hira if reading_hira else surface
        return 0, mora_count, marked, "default"

    def analyze(
        self,
        text: str,
        separator: str = "　",
    ) -> Tuple[str, List[Dict]]:
        """
        テキスト全体のアクセント解析を行う。

        Args:
            text:      解析テキスト
            separator: 形態素間の区切り文字

        Returns:
            (accent_string, morpheme_details)
            accent_string: 「　」区切りのアクセント記号付きひらがな文字列
            morpheme_details: 各形態素の詳細 list of dict
        """
        morphemes = self.parse_morphemes(text)
        if not morphemes:
            return "", []

        parts   = []
        details = []

        for m in morphemes:
            surface      = m["surface"]
            reading_kata = m["reading_kata"]
            reading_hira = m["reading_hira"]
            pos          = m["pos"]

            if not reading_hira:
                # 読みなし（記号・数字など）
                parts.append(surface)
                details.append({**m, "accent_type": 0, "marked_kana": surface, "source": "noreading"})
                continue

            at, mc, marked, src = self.get_accent_for_morpheme(
                surface, reading_kata, pos, reading_hira
            )
            parts.append(marked)
            details.append({
                **m,
                "accent_type": at,
                "mora_count":  mc,
                "marked_kana": marked,
                "source":      src,
            })

        return separator.join(parts), details

    def format_detail_report(self, details: List[Dict]) -> str:
        """形態素詳細をテキスト形式でフォーマットする"""
        lines = []
        for d in details:
            src_mark = {
                "db_reviewed":  "✅DB確認済",
                "db_predicted": "📋DB予測",
                "pyopenjtalk":  "🔮pyopenjtalk",
                "pyopenjtalk+marine": "🔮pyopenjtalk+marine",
                "default":      "⚪デフォルト",
                "noreading":    "―",
            }.get(d.get("source", ""), "?")

            lines.append(
                f"  {d['surface']:10} → {d.get('marked_kana', ''):20}"
                f"  [{d['pos']}]  {src_mark}"
            )
        return "\n".join(lines)
