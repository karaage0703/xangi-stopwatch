# xangi-stopwatchのセットアップ詳細

初めて導入する方は、[READMEの「はじめに」](README.md#はじめに)から進めてください。[xangi本体](https://github.com/karaage0703/xangi)のセットアップ後、Web UIの「拡張」→「xangi-stopwatch」→「追加」で専用のセットアップ会話が開きます。

この文書は、その会話を担当するAIと手動導入する方向けの詳細手順です。通常の利用者が、先にリポジトリをcloneしたり以下のコマンドを手作業で実行したりする必要はありません。xangi本体の導入手順は[xangiのQuickstart](https://github.com/karaage0703/xangi#quickstart)を参照してください。

## セットアップの進め方

1. xangi本体とAIバックエンドが利用できることを確認します。接続方式（初回はUSB推奨）、StopWatchを接続するホスト、音声サービスの有無を確認します。
2. xangiが取得したこのリポジトリで `uv sync --locked --no-dev` を実行します。手動導入の場合は、先にこのリポジトリを取得します。
3. [ファームウェアの手順](firmware/README.md)に従い、選んだ接続方式のファームを準備します。書き込み先と、既存アプリが置き換わることを利用者へ説明し、確認してから書き込みます。
4. `~/.xangi/xangi-stopwatch/config.json` に、以下のUSBまたはTailnetの接続設定を作ります。既存設定がある場合は内容を確認して必要な項目だけ変更します。
5. xangiの拡張管理から、このcheckoutの `xangi-extension.json` を登録して起動します。登録済みの場合は重複登録せず、設定の反映に必要な操作を行います。操作方法は利用中のxangiのヘルプで確認します。
6. xangi経由で拡張の `/api/health` を確認し、`connected` がtrueになることを確認します。未設定・未接続のままセットアップ完了とはしません。
7. 以下の[共通音声サービス](#共通音声サービス)と[会話設定](#本体マイクで単独会話)を準備します。既存サービスがあれば設定と稼働状態を確認して利用します。
8. Web UIの「拡張」→「xangi-stopwatch」→「開く」でAgent・声・顔を選び、設定を保存します。本体のAボタンで録音・送信し、返答が音声で再生されることを利用者と確認します。

音量はxangiのStopWatch拡張画面で変更し、「保存」を押します。初期値25、0で消音です。本体の再起動後も保持されます。

認証トークンはxangiが起動時に渡します。ブラウザから拡張の内部HTTPへ直接接続しません。Stackchan拡張のインストールは不要です。

## USB

```json
{"transport":"usb","port":"/dev/serial/by-id/StopWatchの実際の識別子"}
```

macOSでは実在する `/dev/cu.usbmodem...` を指定します。自動でUSBを選ばないため、Stackchanのポートを誤って開くことを避けられます。転送速度は921600bpsです。切断後は指定ポートへ再接続します。

## Tailnet

```json
{"transport":"tailnet","bind":"100.64.0.1","peer":"100.64.0.2","port":18766}
```

値は例です。`bind`はホスト自身、`peer`はStopWatchの実際のTailnet IPv4へ置き換えます。100.64.0.0/10以外へのbind・接続元設定は拒否します。指定peer以外のTCP接続も拒否します。TailnetのACLでは、この端末からこのホストの指定ポートへの通信だけを許可してください。端末プロトコル自体に追加のパスワードはなく、Tailnetの認証・アクセス制御を使います。

StopWatchはiPhoneのテザリングでインターネットへ接続し、MicroLink経由でホストの18766へ逆接続します。Stackchanの既定18765とは独立しています。StopWatchの初回Tailnet登録後に得たIPを`peer`へ指定し、拡張を起動し直します。

設定がない場合も拡張は起動しますが `configuration=unconfigured`、`connected=false` です。設定変更は拡張の再起動で反映します。接続先の編集は設定ファイルで行います。


日常の操作・音量設定・トラブル対処は [使い方](docs/usage.md) を参照してください。

## 本体マイクで単独会話

マイク対応ファームを使い、接続設定へ次を追加します。ブラウザは設定時だけ使用し、会話は本体のA/Bボタンで操作します。Aで録音・送信、録音中のBで取消、それ以外のBでキャラ切替です。

```json
{
  "conversation": {
    "provider": "voicevox",
    "voice_url": "http://127.0.0.1:4174",
    "agent_id": "xangi:default",
    "speaker": 1,
    "image_closed": "assets/xangi-avatar/closed.png",
    "image_open": "assets/xangi-avatar/open.png"
  }
}
```

`voice_url`は共通音声サービスのURLです（`/stt`・`/tts`）。Agent、言語、声、顔はxangiのStopWatch設定画面から保存でき、拡張の再起動は不要です。録音・会話処理中の変更は拒否します。Agent切替や保存後は専用の新しい会話セッションになります。


### 共通音声サービス

WhisperとVOICEVOXへの窓口を、独立した共通プロセスで起動します。

```bash
uv sync --locked --extra voice
uv run --locked --extra voice python -m xangi_stopwatch.voice_worker
```

既定はlocalhost:4174です。別途VOICEVOX Engineをlocalhost:50021で起動してください。常駐にはPM2やsystemdを使い、上記プロセスを独立管理します。Avatarにも`AVATAR_VOICE_URL=http://127.0.0.1:4174`を設定すると同じサービスを共有でき、Avatarの停止で音声サービスが終了しません。既存の4174番プロセスがある場合は二重起動せず、起動主体を切り替えます。

- `XANGI_VOICE_HOST` / `XANGI_VOICE_PORT`: bind先（既定127.0.0.1:4174）。認証のない内部サービスなので公開しないでください。
- `XANGI_VOICEVOX_URL`: VOICEVOX Engine（既定http://127.0.0.1:50021）。
- `XANGI_WHISPER_MODEL` / `XANGI_WHISPER_DEVICE` / `XANGI_WHISPER_COMPUTE`: 既定medium / auto / int8（CPU）。初回にモデルを取得します。
- Piperを使う場合は`XANGI_VOICE_ROOT`または`XANGI_PIPER_BIN`・`XANGI_PIPER_MODEL`・`XANGI_PIPER_CONFIG`で既存資産を指定します。モデルやVOICEVOX本体は同梱していません。

StopWatch設定ファイルの`voicevox_url`（conversationの外）は声一覧の取得先です。既定はlocalhost:50021で、音声サービスの`XANGI_VOICEVOX_URL`と揃えます。

WiFi利用では上記をTailnet接続設定と組み合わせます。iPhoneはテザリングの親機として使い、StopWatch→Tailnet→サーバーで通信します。USB専用ファームでは動きません。StopWatch専用の認証キーで登録してください。他の端末の一回限りのキーや端末鍵を流用しません。

### 顔画像

選択したAgentのworkspaceId（未指定時はdefault）のワークスペース内に待機画像と口開き画像を置き、次の固定パスを使います: `assets/xangi-avatar/closed.png` / `assets/xangi-avatar/open.png`。画像ファイルは利用者が用意します。既存のワークスペース画像も利用できます。画像を確認してから保存してください。画像はPNG形式、各20MB以下とし、StopWatch用に466×466 JPEGへ変換します（縦横比を維持、余白は黒）。絶対パス・ワークスペース外へ出るパスやsymlink・偽の画像は拒否します。画像の差し替え後は設定を保存するか再接続すると本体へ反映します。

### WhisperのGPU対応

既定モデルは`medium`です。`XANGI_WHISPER_DEVICE=auto`はCTranslate2のCUDA対応を確認し、使えない場合はPyTorch CUDA、それも使えなければCPU/int8を選びます。PyTorch経路にはCUDA対応のPyTorchと`openai-whisper`が必要です。既存のGPU環境のPythonで`src/xangi_stopwatch/voice_worker.py`を起動できます。`cuda`を明示するとGPUが使えない場合はエラーになります。モデル読込後の`GET /health`に実際の`whisperBackend`・`whisperDevice`を返します。

初回Wi-Fi登録・接続の復旧は、USB設定対応のTailnetファームを書き込んだ後、設定画面からUSB設定用HTMLをダウンロードしてPCで行えます。SSID・パスワードのファーム埋込みは不要です。接続後のWi-Fi追加・切替も[使い方](docs/usage.md#wi-fiを切り替える)を参照してください。Tailscaleの登録とサーバー接続先は共通です。

## 拡張の更新

公開リポジトリから登録した拡張は「更新を確認」から更新できます。更新準備は `scripts/prepare-update` が`uv sync --locked --no-dev`を実行します。停止・起動・正常性確認・失敗時の復旧はxangi本体が行います。
