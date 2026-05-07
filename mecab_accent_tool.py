# coding=utf-8
"""
MeCab アクセント辞書エディタ
====================================
ipadic 全辞書にアクセント情報を追加・管理するスタンドアロンツール。

起動方法:
  python mecab_accent_tool.py
  または launch_tool.bat をダブルクリック

機能:
  ① 単語追加・編集    … 手動でアクセント型を登録
  ② 検索・一覧        … 登録済みエントリの参照・確認・削除
  ③ ipadic 一括処理   … 全 ipadic CSV ファイルのアクセント自動予測
  ④ エクスポート      … MeCab ユーザー辞書 CSV + .dic コンパイル
  ⑤ アクセントテスト  … MeCab + DB でテキストを解析してアクセント表示
"""

import os
import sys
import threading

import gradio as gr

# ── パス設定 ─────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

DATA_DIR   = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
DB_PATH    = os.path.join(DATA_DIR,   "accent.db")

IPADIC_DIR       = r"C:\Program Files\MeCab\dic\ipadic"
MECAB_DICT_INDEX = r"C:\Program Files\MeCab\bin\mecab-dict-index.exe"

OUTPUT_CSV = os.path.join(OUTPUT_DIR, "mecab_accent.csv")
OUTPUT_DIC = os.path.join(OUTPUT_DIR, "mecab_accent.dic")
USER_DICT_JSON = os.path.join(SCRIPT_DIR, "..", "Qwen3-TTS-JP-MeCab", "user_dict.json")

os.makedirs(DATA_DIR,   exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── コアモジュール読み込み ────────────────────────────────────

from core.accent_db        import AccentDB
from core.accent_predictor import (
    AccentPredictor, predict_from_reading,
    mark_accent, count_morae, accent_type_name,
    katakana_to_hiragana, hiragana_to_katakana,
    split_morae, predict_all_phrases,
    OPENJTALK_AVAILABLE,
)
from core.batch_processor  import BatchProcessor, IPADIC_CSV_FILES, POS_PRIORITY
from core.mecab_analyzer   import MeCabAnalyzer, MECAB_AVAILABLE
from core.csv_exporter     import CsvExporter

# ── グローバル初期化 ──────────────────────────────────────────

_db        = AccentDB(DB_PATH)
_processor = BatchProcessor(_db, IPADIC_DIR)
_analyzer  = MeCabAnalyzer(_db, OUTPUT_DIC)
_exporter  = CsvExporter(_db, OUTPUT_DIR, MECAB_DICT_INDEX, IPADIC_DIR)
_predictor = AccentPredictor()

print(f"[INFO] DB: {DB_PATH}")
print(f"[INFO] MeCab: {'✅' if MECAB_AVAILABLE else '❌'}")
print(f"[INFO] pyopenjtalk: {'✅' if OPENJTALK_AVAILABLE else '❌'}")
stats = _db.stats()
print(f"[INFO] 登録済み: {stats.get('total', 0):,} 件 (確認済: {stats.get('reviewed', 0):,} 件)")


# ══════════════════════════════════════════════════════════════
#  共通ユーティリティ
# ══════════════════════════════════════════════════════════════

_TABLE_HEADERS = ["表層形", "読み（カタカナ）", "品詞", "アクセント型", "記号付き", "確認済", "ソース", "CSVファイル"]
_BATCH_RUNNING = threading.Event()


def _fmt_entry_row(entry: dict) -> list:
    reading_hira = katakana_to_hiragana(entry.get("reading_kata", ""))
    marked       = mark_accent(reading_hira, entry.get("accent_type", 0))
    return [
        entry.get("surface",      ""),
        entry.get("reading_kata", ""),
        entry.get("pos",          ""),
        str(entry.get("accent_type", 0)),
        marked,
        "✅" if entry.get("reviewed") else "",
        entry.get("source",     ""),
        entry.get("ipadic_csv", ""),
    ]


def _fmt_table(entries: list) -> list:
    return [_fmt_entry_row(e) for e in entries]


def _db_stats_text() -> str:
    s = _db.stats()
    lines = [
        f"**総エントリ数:** {s.get('total', 0):,} 件",
        f"**確認済み:** {s.get('reviewed', 0):,} 件",
        f"**品詞数:** {s.get('pos_count', 0)} 種",
    ]
    by_src = s.get("by_source", {})
    if by_src:
        lines.append("**ソース別:**")
        for src, cnt in by_src.items():
            lines.append(f"  - {src}: {cnt:,} 件")
    return "\n".join(lines)


POS_CHOICES = ["名詞", "動詞", "形容詞", "副詞", "助詞", "助動詞", "接続詞", "感動詞", "接頭詞", "接尾詞", "記号"]
SOURCE_CHOICES = ["", "manual", "pyopenjtalk", "pyopenjtalk+marine", "default"]


# ══════════════════════════════════════════════════════════════
#  Tab① 単語追加・編集
# ══════════════════════════════════════════════════════════════

def tab1_auto_accent(reading_hira: str):
    reading_hira = (reading_hira or "").strip()
    if not reading_hira:
        return "0", "", "", "読みを入力してください"
    at, mc, conf, src = predict_from_reading(reading_hira)
    type_name = accent_type_name(at, mc)
    marked    = mark_accent(reading_hira, at)
    phrases   = predict_all_phrases(reading_hira)
    phrase_info = ""
    if len(phrases) > 1:
        phrase_info = "  全フレーズ: " + " / ".join(
            f"{p['marked_kana']}（type={p['accent_type']}）" for p in phrases
        )
    return (
        str(at),
        marked,
        f"{type_name}（{mc}拍）{phrase_info}",
        f"ソース: {src}  信頼度: {conf:.0%}",
    )


def tab1_preview(reading_hira: str, accent_str: str):
    reading_hira = (reading_hira or "").strip()
    if not reading_hira:
        return ""
    try:
        at = int(accent_str or "0")
    except ValueError:
        return "アクセント型は整数で入力"
    mc = count_morae(reading_hira)
    return f"{mark_accent(reading_hira, at)}　[{accent_type_name(at, mc)}, {mc}拍]"


def tab1_add(surface, reading_hira, accent_str, pos, note, pos2_in):
    surface      = (surface      or "").strip()
    reading_hira = (reading_hira or "").strip()
    if not surface:
        return "❌ 表層形を入力してください"
    if not reading_hira:
        return "❌ 読み（ひらがな）を入力してください"
    try:
        at = int(accent_str or "0")
    except ValueError:
        return "❌ アクセント型は 0 以上の整数で入力してください"

    reading_kata = hiragana_to_katakana(reading_hira)
    mc = count_morae(reading_hira)

    _db.upsert({
        "surface":      surface,
        "reading_kata": reading_kata,
        "pos":          pos or "名詞",
        "pos2":         pos2_in or "固有名詞",
        "left_id":      1288,
        "right_id":     1288,
        "cost":         4000,
        "accent_type":  at,
        "mora_count":   mc,
        "confidence":   1.0,
        "source":       "manual",
        "reviewed":     1,
        "note":         (note or "").strip(),
        "ipadic_csv":   "manual",
    })
    marked = mark_accent(reading_hira, at)
    return f"✅ 登録完了: 「{surface}」→「{marked}」（{accent_type_name(at, mc)}）"


# ══════════════════════════════════════════════════════════════
#  Tab② 検索・一覧
# ══════════════════════════════════════════════════════════════

_PAGE_SIZE = 100


def tab2_search(surface_q, pos_f, source_f, reviewed_f, page_n):
    reviewed_int = {"全て": -1, "未確認": 0, "確認済": 1}.get(reviewed_f, -1)
    try:
        page = max(1, int(page_n or 1))
    except ValueError:
        page = 1
    offset  = (page - 1) * _PAGE_SIZE
    rows, total = _db.search(
        surface_q     = surface_q or "",
        pos_filter    = pos_f if pos_f != "全て" else "",
        source_filter = source_f or "",
        reviewed_filter = reviewed_int,
        limit         = _PAGE_SIZE,
        offset        = offset,
    )
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    info = f"**{total:,} 件 / ページ {page}/{total_pages}**"
    return _fmt_table(rows), info


def tab2_delete(surface, pos, reading_kata):
    surface      = (surface      or "").strip()
    pos          = (pos          or "").strip()
    reading_kata = (reading_kata or "").strip()
    if not surface:
        return "❌ 表層形を入力してください"
    deleted = _db.delete(surface, pos, reading_kata)
    return f"✅ {deleted} 件削除しました" if deleted else f"❌ 見つかりません: 「{surface}」"


def tab2_mark_reviewed(surface, pos, reading_kata, reviewed_val):
    surface      = (surface      or "").strip()
    reading_kata = (reading_kata or "").strip()
    if not surface:
        return "❌ 表層形を入力してください"
    _db.mark_reviewed(surface, pos or "", reading_kata, reviewed=bool(reviewed_val))
    return f"✅ 「{surface}」を{'確認済' if reviewed_val else '未確認'}にしました"


def tab2_import(json_path):
    json_path = (json_path or "").strip()
    ins, skip, msg = _processor.import_from_user_dict_json(json_path, overwrite=True)
    return msg


# ══════════════════════════════════════════════════════════════
#  Tab③ ipadic 一括処理
# ══════════════════════════════════════════════════════════════

def tab3_get_csv_status():
    """CSVファイルのステータステーブルを返す"""
    files   = _processor.available_csv_files()
    rows    = []
    choices = []
    for f in files:
        status = f"✅ {f['processed']:,}件" if f["processed"] > 0 else "未処理"
        rows.append([f["filename"], f"{f['line_count']:,}", status])
        choices.append(f["filename"])
    return rows, choices


def tab3_run_batch(selected_files, pos_filter_list, overwrite, progress=gr.Progress()):
    """選択したCSVファイルをバッチ処理する（ジェネレータ関数）"""
    if _BATCH_RUNNING.is_set():
        yield "⚠️ すでに処理が実行中です。完了するまでお待ちください。"
        return

    if not selected_files:
        yield "❌ 処理するCSVファイルを選択してください。"
        return

    if not OPENJTALK_AVAILABLE:
        yield "❌ pyopenjtalk が利用できません。インストールしてください。"
        return

    _BATCH_RUNNING.set()
    log_lines = []

    try:
        pos_filter = pos_filter_list if pos_filter_list else None
        total_files = len(selected_files)

        for prog in _processor.process_multiple(selected_files, overwrite=overwrite, pos_filter=pos_filter):
            if "error" in prog:
                log_lines.append(f"❌ エラー: {prog['error']}")
                yield "\n".join(log_lines)
                continue

            if "all_done" in prog:
                log_lines.append(
                    f"\n✅ 全処理完了！\n"
                    f"  処理ファイル数: {prog['total_files']}\n"
                    f"  追加: {prog['total_inserted']:,} 件\n"
                    f"  スキップ: {prog['total_skipped']:,} 件"
                )
                yield "\n".join(log_lines)
                break

            if "done" in prog:
                fname = prog.get("current_file", "")
                log_lines.append(
                    f"  ✅ {fname}: 追加 {prog['inserted']:,} 件 / スキップ {prog['skipped']:,} 件"
                )
            elif "status" in prog:
                log_lines.append(f"▶ {prog['status']}")
            elif "processed" in prog:
                pct = prog["processed"] / max(prog["total"], 1) * 100
                log_lines_tail = log_lines[-3:] if log_lines else []
                last_line = (
                    f"  {prog.get('current_file', '')}: "
                    f"{prog['processed']:,}/{prog['total']:,} ({pct:.0f}%) "
                    f"— 追加 {prog['inserted']:,}"
                )
                # 最終行だけ更新（ログが膨大にならないよう）
                if log_lines and log_lines[-1].startswith("  ") and "%" in log_lines[-1]:
                    log_lines[-1] = last_line
                else:
                    log_lines.append(last_line)

            progress(
                prog.get("file_idx", 0) / max(total_files, 1),
                desc=f"{prog.get('current_file', '')}",
            )
            yield "\n".join(log_lines[-30:])  # 最後30行だけ表示

    finally:
        _BATCH_RUNNING.clear()


def tab3_stop_batch():
    _BATCH_RUNNING.clear()
    return "⏹ 処理を停止しました（現在のバッチ完了後に停止）"


# ══════════════════════════════════════════════════════════════
#  Tab④ エクスポート・コンパイル
# ══════════════════════════════════════════════════════════════

def tab4_export(reviewed_only, pos_filter, manual_cost_str, progress=gr.Progress()):
    try:
        m_cost = int(manual_cost_str or "4000")
    except ValueError:
        m_cost = 4000

    pos_f   = pos_filter if pos_filter and pos_filter != "全て" else None
    written = 0
    status  = ""

    for prog in _exporter.export_csv(
        reviewed_only=reviewed_only,
        pos_filter=pos_f,
        manual_cost=m_cost,
    ):
        written = prog.get("written", written)
        if prog.get("done"):
            status = f"✅ CSV エクスポート完了: {written:,} 件\n出力先: {prog['csv_path']}"
        else:
            progress(written / max(written + 1, 1), desc=f"{written:,} 件書き込み中...")

    return status


def tab4_compile(csv_filename, dic_filename):
    result = _exporter.compile_dic(
        csv_filename=csv_filename or "mecab_accent.csv",
        dic_filename=dic_filename or "mecab_accent.dic",
    )
    return result["message"]


def tab4_export_and_compile(reviewed_only, manual_cost_str, progress=gr.Progress()):
    try:
        m_cost = int(manual_cost_str or "4000")
    except ValueError:
        m_cost = 4000

    log = []
    for prog in _exporter.export_and_compile(reviewed_only=reviewed_only, manual_cost=m_cost):
        status = prog.get("status", "")
        if status:
            log.append(status)
        progress(0.5 if "コンパイル" in status else 0.1, desc=status[:50])

    # .dic を analyzer に反映
    if os.path.exists(OUTPUT_DIC):
        _analyzer.compiled_dic     = OUTPUT_DIC
        _analyzer._tagger_with_dic = None  # キャッシュリセット

    return "\n".join(log)


# ══════════════════════════════════════════════════════════════
#  Tab⑤ アクセントテスト
# ══════════════════════════════════════════════════════════════

def tab5_analyze(text):
    text = (text or "").strip()
    if not text:
        return "", ""
    if not MECAB_AVAILABLE:
        return "❌ MeCab が利用できません", ""

    accent_str, details = _analyzer.analyze(text)
    report              = _analyzer.format_detail_report(details)
    return accent_str, report


# ══════════════════════════════════════════════════════════════
#  Gradio UI 構築
# ══════════════════════════════════════════════════════════════

_STATUS_CHOICES  = ["全て", "未確認", "確認済"]
_BATCH_CSV_TABLE_HEADERS = ["ファイル名", "行数", "処理状況"]

with gr.Blocks(title="MeCab アクセント辞書エディタ") as app:

    gr.Markdown(
        "# MeCab アクセント辞書エディタ\n"
        "ipadic 全辞書にアクセント情報を追加・管理します。  \n"
        f"DB: `{DB_PATH}`　　ipadic: `{IPADIC_DIR}`"
    )

    # ── Tab① 単語追加・編集 ──────────────────────────────────
    with gr.Tab("① 単語追加・編集"):
        gr.Markdown("### 単語のアクセント型を手動登録します")
        with gr.Row():
            with gr.Column(scale=2):
                t1_surface    = gr.Textbox(label="表層形（漢字・原文）", placeholder="例: 伝の心")
                t1_reading    = gr.Textbox(label="読み（ひらがな）",     placeholder="例: でんのしん")
                with gr.Row():
                    t1_accent  = gr.Textbox(label="アクセント型（数値）", value="0", scale=1)
                    t1_auto    = gr.Button("pyopenjtalk 自動取得", variant="secondary", scale=2)
                with gr.Row():
                    t1_pos     = gr.Dropdown(label="品詞",      choices=POS_CHOICES, value="名詞", scale=1)
                    t1_pos2    = gr.Textbox(label="品詞細分類1", value="固有名詞",     scale=1)
                t1_note        = gr.Textbox(label="メモ（任意）")
                t1_add         = gr.Button("辞書に追加 / 更新", variant="primary")
                t1_status      = gr.Textbox(label="ステータス", interactive=False)

            with gr.Column(scale=1):
                gr.Markdown("#### アクセント確認")
                t1_preview     = gr.Textbox(label="プレビュー（↑=上昇　↓=下降）",  interactive=False, lines=2)
                t1_type_name   = gr.Textbox(label="型名・モーラ数",                  interactive=False)
                t1_method      = gr.Textbox(label="取得方法・信頼度",                interactive=False)
                gr.Markdown(
                    "**アクセント型:**\n"
                    "- `0` 平板型　`1` 頭高型\n"
                    "- `N` N拍目まで高（中高/尾高）\n\n"
                    "↑ = 低→高　↓ = 高→低"
                )

    # ── Tab② 検索・一覧 ─────────────────────────────────────
    with gr.Tab("② 検索・一覧"):
        gr.Markdown("### 登録済みエントリの検索・確認・削除")
        with gr.Row():
            t2_surface_q = gr.Textbox(label="表層形（部分一致）", scale=3)
            t2_pos_f     = gr.Dropdown(label="品詞", choices=["全て"] + POS_CHOICES, value="全て", scale=1)
            t2_source_f  = gr.Dropdown(label="ソース", choices=SOURCE_CHOICES, value="", scale=1)
            t2_reviewed_f = gr.Dropdown(label="確認状態", choices=_STATUS_CHOICES, value="全て", scale=1)
        with gr.Row():
            t2_page      = gr.Number(label="ページ", value=1, minimum=1, precision=0, scale=1)
            t2_search_btn = gr.Button("検索", variant="primary", scale=2)
        t2_info  = gr.Markdown("")
        t2_table = gr.Dataframe(
            headers=_TABLE_HEADERS,
            value=[],
            interactive=False,
            label=f"検索結果（最大 {_PAGE_SIZE} 件）",
        )

        gr.Markdown("---")
        gr.Markdown("### 削除・確認状態変更")
        with gr.Row():
            t2_del_surface = gr.Textbox(label="表層形",       placeholder="例: 伝の心", scale=2)
            t2_del_pos     = gr.Textbox(label="品詞（省略可）", placeholder="名詞",     scale=1)
            t2_del_reading = gr.Textbox(label="読み（省略可）", placeholder="カタカナ", scale=1)
        with gr.Row():
            t2_del_btn     = gr.Button("削除", variant="stop", scale=1)
            t2_reviewed_val = gr.Checkbox(label="確認済にする", value=True, scale=1)
            t2_mark_btn    = gr.Button("確認状態を変更", variant="secondary", scale=1)
        t2_op_status = gr.Textbox(label="操作結果", interactive=False)

        gr.Markdown("---")
        gr.Markdown("### user_dict.json からのインポート")
        with gr.Row():
            t2_import_path = gr.Textbox(
                label="user_dict.json のパス",
                value=os.path.normpath(USER_DICT_JSON),
                scale=3,
            )
            t2_import_btn = gr.Button("インポート", scale=1)
        t2_import_status = gr.Textbox(label="インポート結果", interactive=False)

        gr.Markdown("---")
        t2_db_stats = gr.Markdown(_db_stats_text())
        t2_refresh_stats = gr.Button("統計を更新")

    # ── Tab③ ipadic 一括処理 ────────────────────────────────
    with gr.Tab("③ ipadic 一括処理"):
        gr.Markdown(
            "### ipadic 全辞書への一括アクセント追加\n"
            "pyopenjtalk-plus でアクセント型を予測し、SQLite DB に保存します。\n"
            f"ipadic ディレクトリ: `{IPADIC_DIR}`"
        )

        _csv_rows_init, _csv_choices_init = tab3_get_csv_status()

        t3_csv_status = gr.Dataframe(
            headers=_BATCH_CSV_TABLE_HEADERS,
            value=_csv_rows_init,
            interactive=False,
            label="ipadic CSV ファイル一覧",
        )
        t3_refresh_csv = gr.Button("一覧を更新")

        gr.Markdown("### 処理設定")
        with gr.Row():
            t3_file_select = gr.CheckboxGroup(
                label="処理するファイル（複数選択可）",
                choices=_csv_choices_init,
                value=[],
            )
        with gr.Row():
            t3_pos_filter  = gr.CheckboxGroup(
                label="処理する品詞（空=全品詞）",
                choices=POS_CHOICES,
                value=[],
                scale=2,
            )
            t3_overwrite   = gr.Checkbox(
                label="既存エントリを上書き",
                value=False,
                info="チェックなし=未処理のみ追加（高速）",
                scale=1,
            )
        with gr.Row():
            t3_select_all  = gr.Button("全て選択", scale=1)
            t3_select_noun = gr.Button("名詞のみ", scale=1)
            t3_start_btn   = gr.Button("▶ バッチ処理開始", variant="primary", scale=2)
            t3_stop_btn    = gr.Button("⏹ 停止", variant="stop", scale=1)

        t3_log = gr.Textbox(
            label="処理ログ",
            lines=15,
            interactive=False,
        )

    # ── Tab④ エクスポート・コンパイル ────────────────────────
    with gr.Tab("④ エクスポート・コンパイル"):
        gr.Markdown(
            "### MeCab ユーザー辞書のビルド\n"
            "DB のエントリを CSV にエクスポートし、mecab-dict-index でコンパイルします。"
        )

        with gr.Row():
            t4_reviewed_only = gr.Checkbox(label="確認済みエントリのみ", value=False, scale=1)
            t4_pos_filter    = gr.Dropdown(
                label="品詞フィルタ（空=全品詞）",
                choices=["全て"] + POS_CHOICES,
                value="全て",
                scale=1,
            )
            t4_manual_cost   = gr.Textbox(
                label="手動登録エントリのコスト",
                value="4000",
                info="小さいほど優先度高（ipadic標準: 5000〜8000）",
                scale=1,
            )

        with gr.Row():
            t4_csv_name = gr.Textbox(label="CSV ファイル名", value="mecab_accent.csv", scale=2)
            t4_dic_name = gr.Textbox(label="DIC ファイル名", value="mecab_accent.dic", scale=2)

        with gr.Row():
            t4_export_btn  = gr.Button("① CSV エクスポートのみ",      variant="secondary", scale=1)
            t4_compile_btn = gr.Button("② DIC コンパイルのみ",         variant="secondary", scale=1)
            t4_both_btn    = gr.Button("① + ② まとめて実行",           variant="primary",   scale=2)

        t4_result = gr.Textbox(label="実行結果", lines=8, interactive=False)

        gr.Markdown("---")
        gr.Markdown(
            f"**出力先:** `{OUTPUT_DIR}`\n"
            f"- CSV: `{OUTPUT_CSV}`\n"
            f"- DIC: `{OUTPUT_DIC}`\n\n"
            f"**mecab-dict-index:** `{MECAB_DICT_INDEX}`\n\n"
            "コンパイル後、TTS ツール等で以下のように使用できます:\n"
            "```python\n"
            f'MeCab.Tagger("-d {IPADIC_DIR} -u {OUTPUT_DIC}")\n'
            "```"
        )

    # ── Tab⑤ アクセントテスト ───────────────────────────────
    with gr.Tab("⑤ アクセントテスト"):
        gr.Markdown(
            "### MeCab + アクセント DB でテキストを解析\n"
            "DB 登録済みの単語はDBのアクセント型を使用。未登録は pyopenjtalk で予測。"
        )
        t5_text = gr.Textbox(
            label="テストテキスト",
            lines=3,
            placeholder="例: 伝の心やオペレートナビは意思伝達装置です。",
            value="伝の心やオペレートナビは意思伝達装置です。",
        )
        t5_analyze_btn = gr.Button("アクセント解析", variant="primary")
        t5_accent_out  = gr.Textbox(
            label="アクセント記号付き読み（↑=上昇　↓=下降）",
            lines=2,
            interactive=False,
        )
        t5_detail_out  = gr.Textbox(
            label="形態素詳細（ソース別）",
            lines=10,
            interactive=False,
        )
        gr.Markdown(
            f"DB: `{DB_PATH}`\n"
            f"コンパイル済み .dic: `{OUTPUT_DIC}`  "
            f"（{'✅ あり' if os.path.exists(OUTPUT_DIC) else '❌ なし — ④でコンパイルしてください'}）"
        )

    # ══════════════════════════════════════════════════════════
    #  イベントハンドラ（全コンポーネント定義後に登録）
    # ══════════════════════════════════════════════════════════

    # Tab① イベント
    t1_auto.click(tab1_auto_accent, [t1_reading], [t1_accent, t1_preview, t1_type_name, t1_method])
    t1_reading.change(tab1_preview, [t1_reading, t1_accent], [t1_preview])
    t1_accent.change(tab1_preview, [t1_reading, t1_accent], [t1_preview])
    t1_add.click(
        tab1_add,
        [t1_surface, t1_reading, t1_accent, t1_pos, t1_note, t1_pos2],
        [t1_status],
    )

    # Tab② イベント
    t2_search_btn.click(
        tab2_search,
        [t2_surface_q, t2_pos_f, t2_source_f, t2_reviewed_f, t2_page],
        [t2_table, t2_info],
    )
    t2_del_btn.click(
        tab2_delete,
        [t2_del_surface, t2_del_pos, t2_del_reading],
        [t2_op_status],
    )
    t2_mark_btn.click(
        tab2_mark_reviewed,
        [t2_del_surface, t2_del_pos, t2_del_reading, t2_reviewed_val],
        [t2_op_status],
    )
    t2_import_btn.click(tab2_import, [t2_import_path], [t2_import_status])
    t2_refresh_stats.click(lambda: _db_stats_text(), [], [t2_db_stats])

    # Tab③ イベント
    t3_refresh_csv.click(
        lambda: tab3_get_csv_status()[0],
        [],
        [t3_csv_status],
    )
    t3_select_all.click(
        lambda: _csv_choices_init,
        [],
        [t3_file_select],
    )
    t3_select_noun.click(
        lambda: [f for f in _csv_choices_init if "Noun" in f],
        [],
        [t3_file_select],
    )
    t3_start_btn.click(
        tab3_run_batch,
        [t3_file_select, t3_pos_filter, t3_overwrite],
        [t3_log],
    )
    t3_stop_btn.click(tab3_stop_batch, [], [t3_log])

    # Tab④ イベント
    t4_export_btn.click(
        tab4_export,
        [t4_reviewed_only, t4_pos_filter, t4_manual_cost],
        [t4_result],
    )
    t4_compile_btn.click(
        tab4_compile,
        [t4_csv_name, t4_dic_name],
        [t4_result],
    )
    t4_both_btn.click(
        tab4_export_and_compile,
        [t4_reviewed_only, t4_manual_cost],
        [t4_result],
    )

    # Tab⑤ イベント
    t5_analyze_btn.click(tab5_analyze, [t5_text], [t5_accent_out, t5_detail_out])


# ══════════════════════════════════════════════════════════════
#  起動
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"[INFO] MeCab アクセント辞書エディタ 起動中...")
    app.launch(server_name="127.0.0.1", server_port=7862, theme=gr.themes.Soft())
