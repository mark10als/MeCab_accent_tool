# MeCab_accent_tool

**日本語** | [English](README_en.md)

MeCab ユーザー辞書にアクセント情報を追加・管理するスタンドアロンツールです。

---

## 使用目的

日本語TTS（音声合成）で正確なアクセントを実現するために、MeCab の単語辞書にアクセント型を付与します。

### なぜ必要か

標準の MeCab（ipadic）には**アクセント情報が含まれていません**。  
日本語TTS で固有名詞や専門用語を正しいアクセントで読み上げるには、  
単語ごとにアクセント型を設定した MeCab ユーザー辞書（`.dic`）が必要です。

### このツールでできること

- **単語のアクセント型を手動登録**: 表層形・読み・アクセント型を入力して登録
- **アクセント自動取得**: pyopenjtalk-plus / marine でアクセント型を自動予測
- **ipadic 一括処理**: ipadic の全 CSV ファイルを処理してアクセントを DB に保存
- **MeCab ユーザー辞書のビルド**: CSV エクスポート → `mecab-dict-index` でコンパイル
- **アクセントテスト**: コンパイルした辞書でテキストを解析して確認

### 連携リポジトリ

[Qwen3-TTS-JP-MeCab](https://github.com/daibo0501/Qwen3-TTS-JP-MeCab) と連携して使用します。  
このツールで生成した `mecab_accent.dic` を Qwen3-TTS-JP-MeCab が自動検出して使用します。

---

## 動作環境

- **OS**: Windows 10/11
- **Python**: 3.10以上（システム Python 推奨）
- **MeCab**: 別途インストール必要（後述）

---

## インストール

### ステップ 1: MeCab 本体のインストール（必須・別途）

1. 以下からインストーラをダウンロードしてインストール:  
   👉 **https://github.com/ikegami-yukino/mecab/releases**  
   （`mecab-64-*.exe` を選択、インストール時に文字コードは **UTF-8** を選択）

2. インストール確認:
   ```cmd
   mecab --version
   ```

3. デフォルトインストールパス:
   ```
   C:\Program Files\MeCab\bin\mecab-dict-index.exe   ← コンパイルツール
   C:\Program Files\MeCab\dic\ipadic\                ← ipadic 辞書 + CSV ソース
   ```

### ステップ 2: リポジトリのクローン

```bash
git clone https://github.com/daibo0501/MeCab_accent_tool.git
cd MeCab_accent_tool
```

### ステップ 3: 必要パッケージのインストール

`install_packages.bat` をダブルクリック、または手動で:

```cmd
:: システム Python で実行
python -m pip install "gradio>=4.0"
python -m pip install "mecab-python3>=1.0"
python -m pip install pyopenjtalk-plus

:: marine は PYTHONUTF8=1 が必要（Windows の文字コード問題を回避）
set PYTHONUTF8=1
python -m pip install marine
set PYTHONUTF8=
```

インストール確認:

```cmd
python -c "import gradio; print('gradio:', gradio.__version__)"
python -c "import MeCab; print('MeCab: OK')"
python -c "import pyopenjtalk; print('pyopenjtalk-plus: OK')"
python -c "import marine; print('marine: OK')"
```

---

## 起動方法

`launch_tool.bat` をダブルクリック、または:

```cmd
python mecab_accent_tool.py
```

ブラウザで `http://127.0.0.1:7862` が開きます。

---

## 操作手順

### タブ① 単語追加・編集

固有名詞や専門用語を手動で登録します。

| 入力欄 | 内容 |
|---|---|
| 表層形 | 漢字・原文（例: `伝の心`） |
| 読み（ひらがな） | 読み仮名（例: `でんのしん`） |
| アクセント型 | 数値で入力（`0`=平板、`1`=頭高、`N`=N拍で下降） |
| 品詞 | ドロップダウンから選択 |

**「pyopenjtalk 自動取得」ボタン**: 読みを入力後クリックするとアクセント型が自動入力されます。  
**「辞書に追加/更新」ボタン**: DB に登録します。

アクセント型の意味:

| 型 | 名前 | 例（5モーラ） | 記号 |
|---|---|---|---|
| 0 | 平板型 | L H H H H | お↑かねもち |
| 1 | 頭高型 | H L L L L | あ↓たま |
| 2 | 中高型(2) | L H L L L | い↑の↓ち |
| 3 | 中高型(3) | L H H L L | で↑んの↓しん |
| N（=モーラ数） | 尾高型 | L H H H H↓ | お↑とこ（語末が下降） |

### タブ② 検索・一覧

- 登録済みエントリを表層形・品詞・確認状態で絞り込み検索
- エントリの削除・確認済みフラグの変更
- `user_dict.json`（Qwen3-TTS-JP-MeCab の既存辞書）からの一括インポート

**インポート手順**:
1. 「user_dict.json のパス」にファイルパスを入力
2. 「インポート」ボタンをクリック
3. 既存エントリが一括で DB に取り込まれる

### タブ③ ipadic 一括処理

ipadic の全 CSV ファイルを処理して、全単語のアクセントを DB に保存します。

> ⚠️ **処理時間**: ipadic 全体（約40万語）の処理には数時間かかります。  
> 「名詞のみ」フィルターで必要な品詞に絞ることを推奨します。

1. 処理するファイルをチェックボックスで選択（「全て選択」「名詞のみ」ボタンあり）
2. 品詞フィルターで絞り込み（空=全品詞）
3. 「▶ バッチ処理開始」をクリック
4. 処理ログでリアルタイム確認

### タブ④ エクスポート・コンパイル

DB の登録内容を MeCab ユーザー辞書に変換します。

1. **「① CSV を生成」**: DB の内容を 14フィールド CSV に書き出す
2. **「② MeCab .dic にコンパイル」**: `mecab-dict-index` で `.dic` ファイルを生成

出力ファイル:
```
output/
  mecab_accent.csv   ← 14フィールド CSV（中間ファイル）
  mecab_accent.dic   ← コンパイル済み MeCab ユーザー辞書
```

コンパイル成功後、`output/mecab_accent.dic` を Qwen3-TTS-JP-MeCab のプロジェクトルートにコピーすると自動検出されます。

### タブ⑤ アクセントテスト

コンパイル済みの `.dic` を使ってテキストを解析し、アクセントを確認します。

- テキストを入力して「アクセント解析」ボタンをクリック
- MeCab の辞書にアクセント型が登録された単語: その値でアクセント表示
- 未登録の単語: pyopenjtalk で予測したアクセントを表示

---

## データ形式

### DB スキーマ（SQLite）

`data/accent.db` に保存されます:

```sql
CREATE TABLE entries (
  id           INTEGER PRIMARY KEY,
  surface      TEXT,       -- 表層形（漢字）
  reading_kata TEXT,       -- 読み（カタカナ）
  pos          TEXT,       -- 品詞
  accent_type  INTEGER,    -- アクセント型（0=平板、1=頭高、N=N拍で下降）
  reviewed     INTEGER,    -- 確認済みフラグ（1=確認済）
  source       TEXT,       -- 登録元（"manual"/"user_dict.json"/CSVファイル名）
  ipadic_csv   TEXT        -- 元の ipadic CSVファイル名
);
```

### CSV フォーマット（14フィールド ipadic 拡張）

```
表層形,左ID,右ID,コスト,品詞,品詞細分類1,品詞細分類2,品詞細分類3,活用型,活用形,原形,読み,発音,アクセント型
伝の心,1288,1288,5000,名詞,固有名詞,一般,*,*,*,伝の心,デンノシン,デンノシン,3
```

---

## ディレクトリ構成

```
MeCab_accent_tool/
├── mecab_accent_tool.py    ← メインアプリ（Gradio UI）
├── launch_tool.bat         ← 起動用バッチファイル
├── install_packages.bat    ← パッケージ一括インストール
├── requirements.txt        ← 必要パッケージ一覧
├── core/
│   ├── accent_db.py        ← SQLite DB 操作
│   ├── accent_predictor.py ← pyopenjtalk-plus / marine アクセント予測
│   ├── batch_processor.py  ← ipadic CSV 一括処理
│   ├── csv_exporter.py     ← MeCab CSV エクスポート + コンパイル
│   └── mecab_analyzer.py   ← MeCab テキスト解析
├── data/
│   └── accent.db           ← SQLite データベース（自動生成）
└── output/
    ├── mecab_accent.csv    ← エクスポート CSV（自動生成）
    └── mecab_accent.dic    ← コンパイル済み辞書（自動生成）
```

---

## 関連パッケージ

| パッケージ | バージョン | 用途 |
|---|---|---|
| [mecab-python3](https://github.com/SamuraiT/mecab-python3) | 1.0以上 | Python から MeCab を使用 |
| [pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk) | 0.4以上 | 読み変換・アクセント予測 |
| [marine](https://github.com/6gsn/marine) | 0.0.6以上 | DNN アクセント予測（精度向上） |
| [gradio](https://github.com/gradio-app/gradio) | 6.0以上 | Web UI |

### 前提ソフトウェア

| ソフトウェア | 用途 | 入手先 |
|---|---|---|
| MeCab (Windows 64bit) | 形態素解析エンジン + ipadic 辞書 | [ikegami-yukino/mecab releases](https://github.com/ikegami-yukino/mecab/releases) |

---

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) の下で公開されています。

### 使用しているオープンソースソフトウェア

| ソフトウェア | ライセンス | 著作権 |
|---|---|---|
| [mecab-python3](https://github.com/SamuraiT/mecab-python3) | BSD License | Copyright SamuraiT |
| [pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk) | MIT License | Copyright tsukumijima |
| [marine](https://github.com/6gsn/marine) | Apache License 2.0 | Copyright 6gsn |
| [gradio](https://github.com/gradio-app/gradio) | Apache License 2.0 | Copyright Gradio Team |
| [ipadic](https://github.com/taku910/mecab) | BSD License | Copyright Nara Institute of Science and Technology |

---

## 免責事項

- 自動取得されたアクセント情報は必ずしも正確ではありません。重要な語は手動で確認してください
- 本ソフトウェアの使用によって生じたいかなる損害についても、開発者は責任を負いません
- 本ソフトウェアは「現状のまま」提供され、いかなる保証も行いません
