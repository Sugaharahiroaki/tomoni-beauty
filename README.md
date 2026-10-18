# TOMONI Beauty

業務委託・面貸しの個人美容師のための Web アプリ（PWA）。
施術後に 30 秒しゃべるだけで、**簡易カルテ・LINEのお礼とお手入れ案内・次回案内・その美容師にしか書けないSNS投稿** を自動で用意し、LINE 公式アカウントの **無料ルート（1対1チャット／Reply）** で送れるようにします。

第1段階（MVP）に加え、第2段階（一斉・セグメント配信、リッチメニュー、予約通知メールの取り込み、空き枠、報酬明細・レシートのOCR、経費集計、簡易簿記の帳簿、開業届・青色申告承認申請書の補助、手取り見込み）と第3段階（複式簿記・決算書転記・会計ソフト向けCSV）まで実装しています。税務機能は記録・集計・書類作成の補助に留め、最終確認は税理士が行う前提です。

さらに、さんちょく管理 v2 の SNS 動画エンジンを移植し、写真・短い動画から **テロップ・ナレーション・BGM 付きの縦動画（リール）を作って Instagram / YouTube ショート / Threads に予約投稿** できます（[docs/REELS.md](docs/REELS.md)）。

- 計画と実装の説明: [docs/PLAN.md](docs/PLAN.md)
- SNS動画（リール）の設計と外部サービスの準備: [docs/REELS.md](docs/REELS.md)
- 経費・帳簿・申告補助の設計: [docs/LEDGER.md](docs/LEDGER.md)
- ホットペッパー連携の調査: [docs/HOTPEPPER.md](docs/HOTPEPPER.md)
- LINE の通数・送信ルート: [docs/LINE.md](docs/LINE.md)
- 確認したいこと・既定値: [docs/QUESTIONS.md](docs/QUESTIONS.md)
- デプロイ: [docs/DEPLOY.md](docs/DEPLOY.md)

## 開発環境

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
cp .env.example .env              # APIキー未設定でもダミーAIで動く
python manage.py migrate
python manage.py createsuperuser  # 任意（/admin/）
python manage.py runserver
```

http://localhost:8000/accounts/signup/ から美容師アカウントを作成 → 基本情報 → LINE（スキップ可）→ インタビュー → 「今日」画面。

録音は HTTPS または localhost でのみ動作します（ブラウザの制約）。スマホ実機で試す場合は `ngrok` 等で HTTPS を用意し、`DJANGO_ALLOWED_HOSTS` と `DJANGO_CSRF_TRUSTED_ORIGINS` を設定してください。

## テスト

```bash
pytest
```

外部 API（Claude / OpenAI / LINE）は呼ばず、SQLite in-memory で実行します。

## 本番で必要な外部サービス

| サービス | 用途 | 環境変数 |
| --- | --- | --- |
| Anthropic Claude API | カルテ構造化・文面・SNS投稿・返信案・個人情報チェック | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` |
| OpenAI 音声認識 | 音声メモ・インタビューの文字起こし | `OPENAI_API_KEY`, `TRANSCRIPTION_MODEL` |
| LINE Messaging API | 美容師ごとのチャネル（設定画面から登録） | — |
| n8n（任意） | 日次処理の起動・通知メール | `INTERNAL_API_TOKEN` |
| FFmpeg ＋ 日本語フォント | SNS動画の作成（サーバーに必須） | `FFMPEG_BIN`, `ENGINE_FONT` |
| Google Gemini | 動画のナレーション（任意） | `GEMINI_API_KEY` |
| Meta / Google のアプリ | Instagram・YouTube・Threads への自動投稿（任意。無ければお試し投稿） | `INSTAGRAM_APP_ID` 等 |

## 設計上の約束（指示書 9 の必須ルール）

- SNS 生成にはカルテを直接渡さず、ホワイトリスト（施術内容・一般化した悩みと結果）だけを渡し、生成後に個人情報チェックを行う。
- 写真・顔出し・ストーリーの各同意を記録し、同意の無い情報は SNS 生成に使えない。
- LINE 送信は必ず美容師の確認後。通数を消費する Push は任意設定・残数表示付き。
- 連絡NG／ブロック／直近送信済み／予約済みの人には案内を送れない。
- ホットペッパー／SALON BOARD へのスクレイピング・自動操作はしない。
- 美容師ごとにデータを分離し、顧客単位・アカウント単位で削除できる。
