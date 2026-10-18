# SNS動画投稿（リール）の設計メモ

さんちょく管理 v2 の「Social Content Engine」を美容師向けに移植したものです（`apps/reels`）。
写真か短い動画を数枚撮る → AIが台本 → FFmpeg で縦動画（テロップ・ナレーション・BGM）→ 確認 → Instagram リール / YouTube ショート / Threads に予約投稿。

## 1. 画面の流れ

```
SNSタブ（/reels/）
  └ 新しい動画（/reels/new/）… 型を選ぶ（おまかせ可）。カルテから開くと掲載OKの写真を素材に取り込む
      └ 作業画面（/reels/<id>/）
          ① 撮る：撮影リスト（型ごとに5〜6枠、構図の線つきカメラ・3秒動画）→「台本をつくる」
          ② 台本を確かめる：場面ごとのテロップ・セリフ・写真の差し替え、CTA、声（AI/自分/なし）、BGM、投稿文
          ③ 動画を確かめる：9:16 プレイヤー、いっしょに出る文章、投稿先
          ④ 投稿：おすすめ時間に予約 / 今すぐ / 日時指定。公開後は再生・いいね・保存の数
  └ 記録（/reels/history/）… 型ごとの平均再生回数、いちばん見られた投稿
  └ 設定（/reels/settings/）… 投稿先をつなぐ、声、ブランド名、いつもの呼びかけ
```

文章だけの投稿（フィード・ストーリーズ・リール台本）は従来どおり `/sns/` で、Instagram 風のプレビュー（フィード／ストーリーズ／台本タイムライン）を追加。

## 2. 型（`apps/reels/recipes.py`）

| 型 | ゴール | 尺 | CTA | 撮影リスト（例） |
|---|---|---|---|---|
| ビフォーアフター | 指名・問い合わせ | 15〜20秒 | 予約・相談 | 仕上がりアップ → 施術前の後ろ姿 → 薬剤 → 手元 → 仕上がりの後ろ姿 |
| 施術のこだわり | 信頼 | 20〜25秒 | フォロー | 仕上がり → カウンセリング手元 → 調合 → 塗布 → 鏡で確認 |
| ホームケア豆知識 | 保存 | 15〜25秒 | 保存 | 結論のアップ → ①②③の手元 |
| スタイリストの思い | ファン化 | 25〜35秒 | フォロー | 後ろ姿 → 道具 → 手元 → 店内 → 仕上がり（人柄エピソードを1〜2個） |
| サロンの日常 | 親近感 | 10〜20秒 | なし/フォロー | 開店前 → 準備 → 施術 → 片付け |

型は「今日の施術メニュー」「投稿の目的」「直近の投稿（同じ型を3回続けない）」から自動で選べます。

## 3. お客様の個人情報・顔の扱い

- 台本の入力に渡すのは、カルテの `sns_safe_fields()`（施術内容・仕上がり）と、ストーリー掲載OKの顧客に限って **一般化した悩みと結果** だけ。顧客名・private_notes・来店日時は渡さない。
- 素材の `face_visible`（顔が写っている）と投稿の `face_allowed`（顧客の `face_ok`。顧客なしなら本人の顔として許可）で、顔が写った素材は顔出しNGのときAIにも渡さず、動画にも使わない。
- 生成後、テロップ・セリフ・投稿文を `apps/ai/pii.py` で検査（顧客名の表記ゆれ・年齢・電話など）。error が残る間は「動画をつくる」を押せない。AIにも違反を伝えて2回まで直させる（`ai.check_script`）。
- AIの声を使う投稿には「※ナレーションはAI音声です。」を自動で付け、YouTube には合成音声フラグを立てる。

## 4. 仕組み

| 部品 | 場所 | 内容 |
|---|---|---|
| 台本 | `ai.py` + `prompts/*.md` | Claude（構造化出力）。素材画像（JPEG 1024px）を見せて、型に沿った scenes/shots/cta/caption/hashtags を返す。APIキー無しは型の見本どおり |
| 動画 | `engine/render.py` | 1080x1920・30fps。写真は Ken Burns（zoompan）、動画は良い2秒から。テロップは drawtext（日本語フォント必須）。BGM はラウドネス正規化＋ナレーション中ダッキング。各カットを個別エンコードして concat |
| ナレーション | `engine/tts.py` | Gemini TTS（`GEMINI_API_KEY`）。文章・声ごとにキャッシュ。本人の声の録音（セリフごと）にも対応。キー無しは声なし |
| 投稿 | `publishing.py` | Instagram Graph（REELS コンテナ→publish）、YouTube Data API（resumable upload、#shorts）、Threads API。未接続は「お試し」 |
| 接続 | `connect.py` | OAuth。トークンは `SecretTextField`（Fernet、`FIELD_ENCRYPTION_KEY`）で暗号化。60日トークンは日次で延長 |
| 定期処理 | `services.housekeeping` | 予約時刻になった投稿の実行、数値の取り込み（6時間ごと）、トークン延長（日次）。`manage.py setup_schedules` で django-q2 に登録、または `manage.py reels_housekeeping --loop` |
| メディア配信 | `apps/core/media_access.py` | `/media/` は Django が権限確認。できあがった動画（`stylist_<id>/reels/renders/`）だけ公開（Instagram が取りに来る）。本番は Nginx の `X-Accel-Redirect` |

## 5. サーバーに必要なもの

- **FFmpeg**（ffmpeg / ffprobe）。Ubuntu: `apt install ffmpeg`
- **日本語フォント**（テロップ）。Ubuntu: `fonts-noto-cjk`（`setup_server.sh` に含む）。別フォントは `ENGINE_FONT`
- `cryptography`（トークン暗号化）、`pillow-heif`（iPhone の HEIC）
- 動画の一時作業場所 `RENDER_WORK_DIR`（公開しない場所）、十分なディスク（1本 20〜60MB）
- django-q2 のワーカー（`qcluster`）。動画作成は1本2〜3分かかるため、本番は必ずワーカーで実行（`Q_SYNC=false`）

## 6. 外部サービスの準備（運営が1回だけ）

戻り先URLはすべて `https://<ドメイン>/reels/connect/<platform>/callback/`。

### Instagram（Meta）
1. https://developers.facebook.com でアプリ（種類：ビジネス）を作り、「Instagram」製品 →「Instagram ログインの API 設定」。
2. ビジネスログイン設定のリダイレクトURLに `…/reels/connect/instagram/callback/` を登録。
3. `INSTAGRAM_APP_ID` `INSTAGRAM_APP_SECRET` を `.env` に。
4. 権限 `instagram_business_basic` `instagram_business_content_publish` `instagram_business_manage_insights`。審査前は Instagram テスターに登録したアカウントだけ接続可（試験運用はこれで開始）。審査にはプライバシーポリシー（`/privacy/`）・利用規約（`/terms/`）・データ削除手順のURLと画面録画が必要。
5. 投稿は Instagram が動画を取りに来る方式。`PUBLIC_MEDIA_BASE_URL`（既定 `SITE_URL/media`）が外から開けること。1アカウント 24時間に100投稿まで。

### YouTube（Google Cloud）
1. プロジェクトを作り **YouTube Data API v3** を有効化。
2. OAuth 同意画面（外部）にアプリ名・プライバシーポリシー・利用規約を登録。スコープ `youtube.upload` `youtube.readonly`。
3. OAuth クライアント（ウェブ）を作り、リダイレクトURIに `…/reels/connect/youtube/callback/`。`YOUTUBE_CLIENT_ID` `YOUTUBE_CLIENT_SECRET`。
4. テスト中はテストユーザーだけ接続可、7日でつなぎ直し。**監査（コンプライアンス審査）を受けるまで、アップロードした動画は非公開になる。** 早めに申請。

### Threads（Meta）
1. ユースケース「Threads API にアクセス」でアプリを作成、コールバックURLに `…/reels/connect/threads/callback/`。
2. 権限 `threads_basic` `threads_content_publish` `threads_manage_insights`。`THREADS_APP_ID` `THREADS_APP_SECRET`。
3. 本文は500文字・話題タグは1つに自動で縮める。

### Gemini（ナレーション）
- `GEMINI_API_KEY`。有料枠で使う（無料枠は入力がサービス改善に使われる場合がある）。モデルは `engine/settings.json`（`gemini-3.1-flash-tts-preview`）。1日の回数上限に注意（セリフの数だけ呼ぶ。同じセリフはキャッシュ）。

### BGM
- `python manage.py import_bgm <フォルダ>`（サブフォルダ名がカテゴリ）または `--flat`（ファイル名から推定）。開発用に `static/bgm_seed/` のサンプルを入れてあるが、**ライセンスは未確認**。本番（`BGM_REQUIRE_LICENSE=true`）では管理画面で「商用利用の条件を確認した」を付けた曲だけ使われる。

## 7. 費用の目安

- 台本: Claude Opus 5.5 で 1本あたり 1〜2万トークン入力（画像込み）＋2〜3千トークン出力 ≒ 10〜15円。Sonnet 5.5 なら半額。
- ナレーション: Gemini TTS 1本（8セリフ・約25秒）≒ 2〜3円。
- 動画作成はサーバーのCPU時間のみ（1本 1〜3分）。

## 8. テスト

`apps/reels/tests/test_reels.py`: 型の選択・撮影リスト、カルテ写真の取り込み（顔出しNG・掲載NGの除外）、見本台本とルール検査（素材ID・個人情報）、台本の修正、BGM選択、投稿文（AI表示・Threads 500文字）、おすすめ時間、エンジンの純粋関数、メディア閲覧権限（本人のみ・公開動画・パス走査）、OAuth開始/コールバック、画面の一連の流れ、テナント分離、個人情報エラーでの動画作成ブロック、FFmpeg がある環境では実際に動画を1本作る。
