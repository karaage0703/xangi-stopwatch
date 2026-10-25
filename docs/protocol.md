# StopWatch設定APIと端末通信

Managed capability: `device.stopwatch`。APIはxangiからのBearer認証を必須とし、127.0.0.1の動的ポートのみで待ち受けます。JSON本文は900,000byteまで。

認証付き`GET /api/settings`は音量・会話状態・直近テキスト・処理時間を返します。`POST /api/settings`は`{"volume":25}`の整数0〜255を受け付けます。`/api/config`は会話設定、`/api/agents`と`/api/speakers`は選択肢、`/api/preview`はワークスペース画像のプレビューです。

画像転送・再生キュー・接続監視は会話制御の内部処理です。外部から端末を専有するAvatar APIは提供しません。音声再生は8–48kHz、mono PCM16、30秒以下・600KB以下です。停止・切断時は処理中の古い返答を破棄します。

端末プロトコルは改行区切りJSON応答。`STATUS`、`AUDIO_STOP`、`SIMG:slot,size`、`SFRAME:slot`、`SANIM:interval,slot,...`、`WAV:size` を使用する。バイナリ送信はready→payload→okの順。TCP接続元を登録済みTailnet peerに制限し、USBは指定ポートのみ利用する。

## マイク

`STATUS`の`microphone`がtrueなら対応。`mic_recording`、`mic_ready`、`mic_id`、`mic_bytes`を返す。録音は16kHz/mono/PCM16 little-endian、最大30秒。

- `MIC_BUTTON:on/off`: 本体Aボタンの手動録音を有効/無効にする。無効化は録音を破棄。
- `MIC_START`: 録音開始。`MIC_STOP`: 録音を確定（送信可能にする）。
- `MIC_CANCEL` / `MIC_CLEAR`: 録音を破棄。`mic_ready`を解除。
- `MIC_READ:offset,count`: 確定した録音から最大16384バイト読み、JSONの`pcm`にhexを返す。

録音の再生や送信はSTOP確定後のみ。録音中のWAV再生は拒否する。接続復帰時は古い録音を破棄してから単独会話を再開する。

### 無線診断（Tailnet版のみ）

`NET_STATUS`は`wifi_status`（Arduino Wi-Fi状態値）、`has_ip`、`clock_ready`を返します。接続前はUSBから確認できます。時刻同期完了後にTailnet登録・接続を開始します。

`STATUS.mic_read_max`は1回の`MIC_READ`で取得できるPCMバイト数です。未提供の場合は1024として扱い、現行ファームは16384を返します。

## 会話の吹き出し

`STATUS.caption: true`を返すファームは`CAPTION:U:<text>`（認識結果）と`CAPTION:A:<text>`（返答）に対応します。改行を除いたUTF-8を送り、空文字で消去します。1行のコマンド上限は4,096バイトです。1ページは12文字×2行で、顔を残して表示します。`CAPTION_MS:<milliseconds>`は返答のページ間隔を500〜30,000msに設定し、認識結果では4秒に戻します。ホストは音声の長さとページ数から返答の間隔を決めます。旧ファームには送信しません。

`GET /api/settings`の`transcript`と`reply`には直近の認識結果・返答を返します。`POST /api/voice-test`は`provider`、`speaker`、`language`を受け、設定を書き換えずテスト文を合成し、base64 WAVを`wav`に返します。本体へ音声を送らず、設定画面で再生します。

`STATUS.mic_base64: true`では`MIC_READ_B64:offset,count`で最大32768バイトのPCMをBase64として取得できます。hex方式より符号化後の転送量を約3分の2に抑えます。未対応ファームは従来の`MIC_READ`を使います。

`STATUS.caption_index: true`では`CAPTION_INDEX:n`で返答の文番号を設定します。長文のページ番号は別に表示し、会話終了・停止時には吹き出しを消します。途中生成中は文数の合計が未確定のため、総文数は表示しません。

## 保存キャラ

`GET /api/config`は現在の設定、`active_character`、保存順の`characters`を返します。
`POST /api/config`で現在のキャラ名・Agent・音声・顔を保存します。
`POST /api/characters`は`action`（`duplicate` / `select` / `delete`）と対象`id`を受けます。複製は保存済みの現在の設定を使います。最後の1件の削除は拒否します。

`STATUS.character_button: true`のファームは録音中以外のBで`{"event":"character_next"}`を通知します。ホストは次の保存キャラへ切り替え、旧会話の音声を破棄します。録音中のBは端末内で録音を破棄し、切替イベントは送りません。

## Wi-Fi設定

`GET /api/network`は選択中の`active`と`profiles`（`id`・`ssid`・`built_in`）を返します。パスワードは返しません。`POST /api/network`は`action: add`と`ssid`・`password`、または`action: select/delete`と`id`を受け付けます。selectの成功は再接続完了ではなく、本体への選択保存と再起動受付です。

Tailnetファーム0.4は`WIFI_LIST`、`WIFI_ADD:<SSIDのUTF-8 hex>,<パスワードのUTF-8 hex>`、`WIFI_SELECT:<id>`、`WIFI_DELETE:<id>`に対応します。hexはコマンド区切りと資格情報を分離するためで、暗号化ではありません。転送保護はTailscaleが担います。Wi-Fiの保存枠は0〜4で、0はビルド時の初期設定です。追加分と選択は本体NVSに保存します。

WIFI_SELECTはACK後に本体を再起動し、選択先だけへ接続します。到達失敗で保存枠を自動変更する処理はありません。無線切断中はUSBからWIFI_SELECTで選び直せます。

`WIFI_RENAME:<id>,<SSIDのUTF-8 hex>` は未選択の保存枠（1〜4）のSSIDだけを変更します。パスワードは保持し、接続先は変更しません。初期枠・選択中の枠・存在しない枠・重複SSIDは拒否します。USBで操作する場合はネットワーク切断中に使用します。

Tailnet版の`NET_STATUS`は`tailnet_state`（0: idle、1: Wi-Fi待ち、2: 接続中、3: 登録中、4: 接続済み、5: 再接続中、6: エラー）、`peer_count`、`tcp_attempts`も返します。Wi-Fi接続・Tailscale接続・会話用TCP接続の進行を切り分けるための診断値です。

## 会話停止とバッテリー（stopwatch-voice-0.5）

- STATUS: `conversation_stop: true`、`battery_percent: 0..100`（取得不能時-1）、`battery_charging: boolean`。
- 返答待ち・再生中のB: 音声を即座に停止し、`{"event":"conversation_stop"}` を通知。バイナリ受信中は読み切り・破棄後に通知してフレーム境界を保つ。
- 停止後のWAVは拒否。ホストが古い会話を中断・片付けた後、`MIC_BUTTON:on` で次の会話を許可する。
- 待機中Bの`character_next`と、録音中Bの録音取消は維持する。

## USB Wi-Fi初回設定（ファーム0.8）

`WIFI_LIST`の`usb_setup: true`が対応の目印です。USB専用の`WIFI_SETUP:<SSID UTF-8 hex>,<password UTF-8 hex>`は、同一SSIDの更新または空き枠への追加と接続先選択を行い、成功応答後に再起動します。Wi-Fi未設定時も利用でき、0番も保存枠として使えます。SSIDは1〜32バイト、passwordは空または8〜63バイト。NULは拒否します。会話中や保存数上限、新規保存失敗時はエラーを返し、資格情報は応答しません。

SSIDとpasswordはNVSの一つの文字列にまとめて保存します。旧形式の保存枠・ビルド時の初期Wi-Fiは、新形式で上書きしていなければ引き続き読みます。新形式の設定を使う場合、旧ファームへ戻すとその設定を読めません。ビルド時の初期設定を引き継ぐ更新では既存の`tailnet_secrets.h`を保持してください。

Tailnet接続中のUSBは`WIFI_LIST`、`WIFI_SETUP`、`WIFI_DELETE`、`NET_STATUS`のみ受け付けます。USBから会話イベントを取り出さず、音声・画面用TCP通信と分離します。`NET_STATUS`の`server_connected`は会話サーバーとのTCP接続状態です。保存成功、Wi-Fi接続成功、サーバー接続成功は別の状態として表示します。
