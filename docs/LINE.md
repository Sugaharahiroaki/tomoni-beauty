# LINE 連携の設計メモ（通数・送信ルート・調査結果）

調査日: 2026-10-18。出典は末尾。

## 1. 通数の事実（LINE公式・2026年10月時点）

| 項目 | 内容 |
| --- | --- |
| プラン（日本・税別） | コミュニケーション ¥0／無料200通／追加不可、ライト ¥5,000／5,000通、スタンダード ¥15,000／30,000通＋従量（2026/10/1 改定: 20万通まで1通3円、超過2.5円） |
| 通数にカウントされる | メッセージ配信（絞り込み・ステップ配信含む、管理画面からでも同じ）、Messaging API の Push／Multicast／Broadcast／Narrowcast |
| カウントされない | LINEチャット（1対1トーク）の送受信、応答メッセージ、あいさつメッセージ、Messaging API の Reply API |
| 数え方 | 送信リクエスト数 × 送信対象人数（吹き出し数ではない）。ブロック中・存在しないIDは非カウント |
| 当月消費の取得 | `GET /v2/bot/message/quota/consumption` → `totalUsage`。**LINE公式アカウントマネージャーから送った分も含む**（概算） |
| 上限の取得 | `GET /v2/bot/message/quota` → `{"type":"limited","value":200}` または `{"type":"none"}` |
| Replyトークン | **1回限り・Webhook受信から1分以内**。再送Webhookのトークンは再送受信から1分（元トークン使用済み／イベントから20分経過後は不可） |
| follow イベント | `follow.isUnblocked` で新規追加かブロック解除かが分かる（完全な精度は保証されない） |
| bot 情報 | `GET /v2/bot/info` → `userId`（U…）, `basicId`（@…）, `displayName`, `chatMode`, `markAsReadMode` |

→ 本アプリは **無料ルート（1対1チャット・Reply）を既定** にし、Push は設定でオンにした美容師だけ・残数表示付きで使う（実装済み）。

## 2. 送信ルートの実装

| ルート | 画面 | 仕組み | 通数 |
| --- | --- | --- | --- |
| コピーしてLINEで開く | 文面 / 返信 | `navigator.clipboard.writeText` → 新規タブで OA Manager のチャット画面URLを開く → 貼り付けて送信 → 戻って「送った」で `Message(route=copy)` を記録 | 消費しない |
| Reply API | 返信 | `InboundMessage.reply_token_valid()`（既定TTL 50秒、残り秒数カウントダウン表示）→ `POST /v2/bot/message/reply` | 消費しない |
| Push API | 文面 / 返信 | `LineChannel.push_enabled` がオンの美容師のみ。`QuotaStatus.would_exceed` なら送信不可。送信後にローカル加算、日次で実測値に同期 | 1通 |

「送った」の記録は手動です。1対1チャットの送信を Webhook で検知する手段は Messaging API に無いためです（管理画面チャットの送信はイベントとして配信されない）。

## 3. 「コピー〜LINE起動」のワンタップ化：調査結果と採用案

| 手段 | 結果 |
| --- | --- |
| Web版 OA Manager の個別チャットURL `https://chat.line.biz/{botUserId}/chat/{userId}` | **公式ドキュメントに記載なし（非公式・実務上の観測）**。`{botUserId}` は `GET /v2/bot/info` の `userId`／Webhook の `destination` と一致。予告なく変わり得るため、`LINE_CHAT_URL_TEMPLATE`（環境変数）と `LineChannel.chat_url_template`（美容師ごと）で差し替え可能にした。形式が崩れた場合はチャット一覧 `https://chat.line.biz/{botUserId}` にフォールバック |
| LINE公式アカウント（管理）アプリのディープリンク | 公式URLスキーム文書・ヘルプのいずれにも **記載なし**。見つからなかっただけで「存在しない」の公式記述も無い |
| `https://line.me/R/oaMessage/@basicId/?text` | **お客様側**（LINEアプリ）が公式アカウントとのトークを開くリンク。美容師側の送信には使えない。第2段階で「友だち追加→このLINEに相談」導線に使える |
| スマホブラウザでの chat.line.biz | 推奨環境は PC の Chrome と明記され、スマホブラウザでの動作は公式保証なし（ログインが必要）。実機確認が必要 |
| Web Share API（`navigator.share`） | 共有シートから LINE を選べるが、開くのは **個人の LINE アプリ**（公式アカウントのチャットではない）。補助ルートとして「共有…」ボタンを用意 |

採用: ①「コピーしてLINEで開く」= クリップボードにコピー → chat.line.biz の該当トークを新規タブで開く（LINE未連携の顧客はコピーのみ）。②「共有…」。③「コピーのみ」。
実機（iOS Safari / Android Chrome）で chat.line.biz の挙動を確認し、不可なら OA Manager アプリを手で開いて貼り付ける運用（コピーのみ）に寄せる。試験運用の確認項目に含める。

## 4. Webhook と顧客の紐付け

1. 友だち追加（follow）／メッセージ受信で `userId` を受け取り、未登録なら `GET /v2/bot/profile/{userId}` で表示名を取って **仮顧客** を作成（`needs_review=True`）。
2. 美容師は顧客詳細で「名前を確認して保存」または「既存のお客様に紐付ける」（`merge_line_shell_into`：受信・送信履歴も移す）。
3. unfollow（ブロック）で `line_blocked_at` を記録 → 送信不可。再follow で解除。
4. 同じ `message.id` の再送は無視。署名検証 NG は 403。

## 5. LINE側の推奨設定

- LINE Official Account Manager › 設定 › 応答設定: **チャット: オン**、応答メッセージ: オフ（返信案はアプリで作る）、あいさつメッセージ: 任意（通数非消費なので活用推奨）。
- Messaging API 設定: Webhook URL = アプリの `設定 › LINE連携` に表示されるURL、「Webhookの利用」オン。
- 通数を使わない告知手段（第2段階で UI 化）: リッチメニューの更新、あいさつメッセージ、LINE VOOM。

## 6. 出典

- https://www.lycbiz.com/jp/service/line-official-account/plan/ （プラン・カウント対象）
- https://www.lycbiz.com/jp/news/line-official-account/20261001/ （追加メッセージ料金改定）
- https://developers.line.biz/en/docs/messaging-api/pricing/
- https://developers.line.biz/ja/tips/2026/05/28/how-to-count-messages/
- https://developers.line.biz/en/reference/messaging-api/#send-reply-message （Replyトークン）
- https://developers.line.biz/en/reference/messaging-api/#get-consumption （consumption に管理画面分を含む）
- https://developers.line.biz/en/reference/messaging-api/#follow-event
- https://developers.line.biz/en/reference/messaging-api/#get-bot-info
- https://developers.line.biz/ja/docs/messaging-api/using-line-url-scheme/ （URLスキームは利用者側）
- https://www.lycbiz.com/jp/manual/OfficialAccountManager/chats/ （トーク画面URL＝oaMessage）
- https://help2.line.me/official_account_jp/web/pc?lang=ja&contentId=20013940 （推奨環境）
- https://zenn.dev/tatsuyasusukida/articles/line-friend-export （chat.line.biz の非公式URL構造）
