# coding=utf-8
"""
アクセント予測モジュール

pyopenjtalk-plus と marine を使って読み仮名からアクセント型を予測する。
marine がインストールされている場合はより高精度な予測が可能。
"""

import re
from typing import Tuple, List, Optional, Dict

# ── ライブラリ読み込み ────────────────────────────────────────

try:
    import pyopenjtalk
    OPENJTALK_AVAILABLE = True
except ImportError:
    pyopenjtalk = None
    OPENJTALK_AVAILABLE = False

# marine は pyopenjtalk-plus がインストール済みの場合に利用可能
try:
    import pyopenjtalk
    # pyopenjtalk-plus は marine が利用可能なとき自動的に使用する
    # extract_fullcontext() の精度が向上する
    _marine_test = pyopenjtalk.extract_fullcontext("テスト")
    MARINE_INTEGRATED = True
except Exception:
    MARINE_INTEGRATED = False

# ── かなユーティリティ ────────────────────────────────────────

_SMALL_KANA = set("ぁぃぅぇぉっゃゅょァィゥェォッャュョ")


def katakana_to_hiragana(text: str) -> str:
    return "".join(
        chr(ord(ch) - 0x60) if 0x30A1 <= ord(ch) <= 0x30F6 else ch
        for ch in text
    )


def hiragana_to_katakana(text: str) -> str:
    return "".join(
        chr(ord(ch) + 0x60) if 0x3041 <= ord(ch) <= 0x3096 else ch
        for ch in text
    )


def split_morae(kana: str) -> List[str]:
    morae, i = [], 0
    while i < len(kana):
        mora = kana[i]
        i += 1
        while i < len(kana) and kana[i] in _SMALL_KANA:
            mora += kana[i]
            i += 1
        morae.append(mora)
    return morae


def count_morae(kana: str) -> int:
    return len(split_morae(kana))


def make_pitch_list(accent_type: int, mora_count: int) -> List[str]:
    """東京式アクセントの H/L ピッチ列を返す"""
    n = mora_count
    if n == 0:
        return []
    if accent_type == 0:
        return ["L"] + ["H"] * (n - 1)
    if accent_type == 1:
        return ["H"] + ["L"] * (n - 1)
    acc = min(accent_type, n)
    return ["L"] + ["H"] * (acc - 1) + ["L"] * (n - acc)


def mark_accent(kana: str, accent_type: int) -> str:
    """かな文字列にアクセント記号（↑↓）を付与して返す"""
    morae  = split_morae(kana)
    n      = len(morae)
    if n == 0:
        return kana
    pitches = make_pitch_list(accent_type, n)
    result  = [morae[0]]
    for i in range(1, n):
        if pitches[i - 1] == "L" and pitches[i] == "H":
            result.append("↑")
        elif pitches[i - 1] == "H" and pitches[i] == "L":
            result.append("↓")
        result.append(morae[i])
    return "".join(result)


def accent_type_name(accent_type: int, mora_count: int) -> str:
    if accent_type == 0:
        return "平板型"
    if accent_type == 1:
        return "頭高型"
    if mora_count > 0 and accent_type >= mora_count:
        return "尾高型"
    return f"中高型({accent_type}拍)"


# ── HTS ラベル解析 ────────────────────────────────────────────

def _parse_hts_labels(labels: list) -> List[Tuple[int, int]]:
    """
    HTS ラベルリストから [(accent_type, mora_count), ...] を抽出する。
    /A:accent_type+mora_pos+mora_count/
    """
    phrases       = []
    last_mora_pos = -1

    for label in labels:
        if not label.strip():
            continue
        p_part = label.split("/")[0]
        try:
            current_phone = p_part.split("-")[1].split("+")[0]
        except (IndexError, AttributeError):
            continue
        if current_phone in ("sil", "pau", "xx", ""):
            last_mora_pos = -1
            continue
        m = re.search(r"/A:(-?\d+)\+(\d+)\+(\d+)/", label)
        if not m:
            continue
        accent_type = max(0, int(m.group(1)))
        mora_pos    = int(m.group(2))
        mora_count  = int(m.group(3))
        if mora_pos == 1 and last_mora_pos != 1:
            phrases.append((accent_type, mora_count))
        last_mora_pos = mora_pos

    return phrases


# ══════════════════════════════════════════════════════════════
#  メイン予測関数
# ══════════════════════════════════════════════════════════════

def predict_from_reading(
    reading_hiragana: str,
    surface: str = "",
) -> Tuple[int, int, float, str]:
    """
    読み仮名（ひらがな）からアクセント型を予測する。

    Args:
        reading_hiragana: ひらがなの読み（例: "でんのしん"）
        surface:          表層形（ログ用途のみ）

    Returns:
        (accent_type, mora_count, confidence, source)
        source: "pyopenjtalk" / "pyopenjtalk+marine" / "default"
    """
    if not reading_hiragana or not reading_hiragana.strip():
        return 0, 0, 0.0, "default"

    reading = reading_hiragana.strip()
    mora_count = count_morae(reading)

    if not OPENJTALK_AVAILABLE:
        return 0, mora_count, 0.0, "default"

    try:
        labels  = pyopenjtalk.extract_fullcontext(reading)
        phrases = _parse_hts_labels(labels)

        if phrases:
            accent_type, _ = phrases[0]
            confidence = 0.85 if MARINE_INTEGRATED else 0.70
            source     = "pyopenjtalk+marine" if MARINE_INTEGRATED else "pyopenjtalk"
            return accent_type, mora_count, confidence, source

        # フレーズ検出なし → 平板型
        return 0, mora_count, 0.3, "default"

    except Exception as e:
        return 0, mora_count, 0.0, f"error:{e}"


def predict_all_phrases(reading_hiragana: str) -> List[Dict]:
    """
    全アクセント句の詳細情報を返す（複合語・長い語向け）

    Returns:
        list of {accent_type, mora_count, kana, marked_kana, type_name}
    """
    if not OPENJTALK_AVAILABLE or not reading_hiragana.strip():
        return []
    try:
        labels   = pyopenjtalk.extract_fullcontext(reading_hiragana)
        phrases  = _parse_hts_labels(labels)
        kana_all = katakana_to_hiragana(pyopenjtalk.g2p(reading_hiragana, kana=True))
        morae    = split_morae(kana_all)

        result, idx = [], 0
        for accent_type, mora_count in phrases:
            chunk = morae[idx : idx + mora_count]
            if chunk:
                kana = "".join(chunk)
                result.append({
                    "accent_type": accent_type,
                    "mora_count":  len(chunk),
                    "kana":        kana,
                    "marked_kana": mark_accent(kana, accent_type),
                    "type_name":   accent_type_name(accent_type, len(chunk)),
                })
            idx += mora_count
        return result
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════
#  AccentPredictor クラス（バッチ処理用）
# ══════════════════════════════════════════════════════════════


class AccentPredictor:
    """バッチ予測とキャッシュ管理を行うクラス"""

    def __init__(self):
        self._cache: Dict[str, Tuple[int, int, float, str]] = {}

    def predict(self, reading_hiragana: str, surface: str = "") -> Tuple[int, int, float, str]:
        """
        キャッシュ付き予測。同じ読みは2回目以降キャッシュから返す。
        """
        key = reading_hiragana.strip()
        if key in self._cache:
            return self._cache[key]
        result = predict_from_reading(key, surface)
        self._cache[key] = result
        return result

    def predict_batch(
        self,
        items: List[Tuple[str, str]],  # [(reading_hiragana, surface), ...]
        progress_callback=None,
    ) -> List[Tuple[int, int, float, str]]:
        """
        バッチ予測。

        Args:
            items:             [(reading_hiragana, surface), ...]
            progress_callback: fn(processed, total) 呼び出し（省略可）

        Returns:
            [(accent_type, mora_count, confidence, source), ...]
        """
        results = []
        total   = len(items)

        for i, (reading, surface) in enumerate(items):
            results.append(self.predict(reading, surface))
            if progress_callback and (i % 100 == 0):
                progress_callback(i, total)

        return results

    def clear_cache(self):
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
