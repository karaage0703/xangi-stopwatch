# StopWatch Avatar受信ファーム

この文書は、[xangi-stopwatchのセットアップ](../README.md#はじめに)で使うファームのビルド・書き込み手順です。通常はxangiのWeb UIの「拡張」からxangi-stopwatchを追加し、専用のセットアップ会話で案内を受けて進めます。ホスト側の準備は[セットアップ詳細](../XANGI_SETUP.md)を参照してください。

StopWatchのセッション一覧ファームを置き換えます。書込み先がStopWatchであることを確認してください。既存watcherのWi-Fi設定の自動移行はしません。

```bash
pio run -d firmware -e stopwatch-main
firmware/scripts/setup_microlink.sh
pio run -d firmware -e stopwatch-main-tailnet
```

Tailnet版は `examples/stopwatch/main/tailnet_secrets.example.h` を同じ場所の `tailnet_secrets.h` にコピーし、StopWatch用Tailscale登録キー・ホストのTailnet IP・ポート18766を設定します。Wi-FiのSSID・パスワードは空欄のままビルドでき、書込み後に[USB設定画面](../docs/usage.md#初回設定と接続の復旧usb)で登録します。従来のWi-Fi埋込み設定も引き続き読み込めます。秘密ファイルはGit対象外です。別端末のNVSや登録済み秘密鍵は流用しません。サンプル値では接続できません。

```bash
pio run -d firmware -e stopwatch-main-tailnet -t upload --upload-port <StopWatchのポート>
```

USB専用運用は `stopwatch-main` を書き込みます。Tailnet接続中もUSBのWi-Fi設定・状態確認は利用できます。映像・音声など他のUSB操作は受け付けません。Aで録音・送信、録音中のBで取消、それ以外のBでキャラを切り替えます。円形画面の四隅は見えません。

pioarduino 55.03.36 / Arduino 3.3.6、M5Unified 0.2.21、M5GFX 0.2.28に固定。MicroLinkはsetupスクリプトで固定commitへcheckoutし、同梱パッチを適用します。

## Wi-Fiの地域設定

ビルド先の地域を指定する場合は、ローカルの `tailnet_secrets.h` で `XANGI_WIFI_COUNTRY_CODE` に2文字のISO国コードを指定します（日本は `"JP"`）。空欄・未定義ならSDKの既定設定を維持します。起動時と無線再初期化時に適用し、接続先APの国情報に従う802.11dも有効にします。指定済みの国コードと一致していれば再設定しません。`NET_STATUS` の `wifi_country_error`（0が正常）、`wifi_country_first`、`wifi_country_channels` で適用状態と探索範囲を確認できます。

## ホスト側の自動接続補助

通常はホストからpingを送らず、端末から接続を開始します。旧ファームを使う場合の一時的な回避策として、ホスト拡張の環境変数 `XANGI_STOPWATCH_PEER_DISCOVERY=1` を指定すると、未接続時だけ10秒間隔で `tailscale ping` を送れます。既定は無効です。

## 起動画面

大きな製品名と日本語の接続段階、経過秒数を表示します。Wi-Fi・時刻同期・暗号化通信・サーバー接続・キャラクター準備を区別し、設定不足や初期化失敗も画面に表示します。キャラクター画像を受け取ると通常画面へ切り替えます。

## 無線の再接続

最後に接続できたAPのBSSID・チャンネルとSSIDをNVSへ保存し、次回は選択中SSIDが一致する場合だけ、その接続先へ直接接続を試します。パスワードや登録キーをキャッシュへ複製せず、接続先情報が変わった場合だけ書き込みます。破損・形式違い・別SSIDのキャッシュは無視します。古い接続先へ繋がらなければ、未接続のまま最大8秒で通常探索へ戻ります。接続済みでIP取得待ちの場合は45秒を確保します。Wi-Fi削除時は接続先キャッシュも破棄します。これは探索の依存を減らす方式であり、相手のWi-Fi機能自体が停止している状態から起動できる保証はありません。

Wi-Fiは接続前に全チャンネルを探索し、同じSSIDでは電波の強いAPを優先します。失敗後の試行では能動探索と受動探索を交互に使います。全体探索で見つからなければSSIDを指定した能動探索も行い、検出したAPのBSSID・チャンネルを使って接続します。再試行はアプリ側で管理し、SDKの再接続と探索の競合を避けます。探索は各回最大15秒で、失敗・未検出時にも通常のSSID指定接続を試します。

接続・IP取得は最大45秒待ちますが、ドライバーがAP未検出を通知し、まだ接続も成立していない場合は早期に再探索へ戻ります。接続済みでIP取得待ちの場合は打ち切りません。未検出時の待機間隔は2秒から最大5秒、それ以外は最大30秒まで広げます。VPN初期化前に未検出が3回連続した場合だけ無線を再初期化します。VPN初期化後は通信ライブラリが使うインターフェースを維持します。Wi-Fiの選択・認証情報はPreferencesから読み込み、再試行のたびにドライバーのフラッシュ設定を書き換えません。時刻同期中・会話接続後の切断も復旧対象です。別の保存SSIDへの自動切替は行いません。

USBの `NET_STATUS` はWi-FiとVPN・サーバーの状態を分けて返します。`wifi_attempts` は明示的な接続試行数（SDK内部の再試行を除く）、`wifi_disconnect_reason` は最後の切断理由コードです（0は記録なし、自身の再試行による切断は除外）。`wifi_scan_hidden` は名前なしAP数、`wifi_scan_channels` は探索で観測したチャンネルのビットマスク（bit nがch n）、`wifi_saved_ap_seen` は保存したAP識別子が探索に現れたかを示します。`wifi_saved_ap_auth`・`wifi_saved_ap_channel` はそのAPの認証方式番号とチャンネルです。保存済み識別子に一致する名前なしAPだけを接続候補にでき、無関係な名前なしAPへは接続を試みません。`wifi_cached_attempts` は保存した接続先への直接接続試行数です。`wifi_radio_restarts` は起動中の無線再初期化回数です。`wifi_scan_count` は全体探索で見つかったAP数（負値は未実施・探索エラー）、`wifi_scan_channel` は接続候補のチャンネル（0は未検出）、`wifi_scan_rssi` は候補の電波強度dBm（未検出は-127）です。周囲のSSIDやパスワードは返しません。`has_ip` はWi-Fi接続とIPv4取得の両方が成立した場合だけtrueです。Wi-Fi接続済みならVPN以降の問題として切り分けてください。

参考: [ESPHomeのfast_connect利用仕様](https://esphome.io/components/wifi/)（利用者向け仕様のみ参照、実装のコピー・依存追加なし）、[Arduino ESP32の探索API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html#wifiscan)、[WiFiManagerの間隔を置く接続再試行](https://github.com/tzapu/WiFiManager/blob/master/WiFiManager.cpp)（MIT、コードのコピー・依存追加なし）、[Arduino ESP32 3.3.6の切断理由別の自動再接続](https://github.com/espressif/arduino-esp32/blob/3.3.6/libraries/WiFi/src/STA.cpp)、[ESP-IDFの全チャンネル探索](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-guides/wifi.html)。

`uv run python scripts/check_firmware_wifi_reconnect.py` で遅いIP取得・圏外からの復帰・再試行間隔・接続後の切断・タイマー桁あふれ、探索結果の選択・SSID指定探索・探索失敗、未検出通知後の早期再試行、VPN初期化後の無線保持、IP取得待ちの保護、キャッシュの保存・再読込・不正値・SSID変更・古い接続先のフォールバック・書込み失敗を模擬検証します。スマホのテザリングOFF→ONと会話サーバーへの復帰は実機で確認が必要です。

管理サーバーへの接続が再試行中でも、保存済みのVPNアドレスと端末情報を使い、相手とのWireGuard認証が成功すれば会話サーバーへの接続を試みます。保存済みの情報がある場合は管理接続の成功を待たずWireGuardを初期化し、保存済みの相手の鍵を再登録します。初回登録前や、相手との暗号化通信を確立できない場合は接続しません。割当済みVPNアドレスは端末の鍵と同じNVS領域に保存し、鍵を再生成する場合は破棄します。TLS接続失敗後は、ソケットの状態にかかわらず暗号化処理のメモリを解放して再試行します。

通信中のWireGuard詳細ログは通常無効です。USBコンソールの出力待ちを通信処理へ持ち込まないためです。`setup_microlink.sh` はパッチ適用後にPlatformIOの該当依存キャッシュを削除するので、パッチ更新後もこのスクリプトを実行してからビルドしてください。

接続先一覧は最後まで調べ、端末と同じサブネットのIPv4アドレスを優先します。Docker等のインターフェースが多くてもLAN接続先を先頭8件の制限で落とさず、認証された探索応答で確認した直接接続先を再起動用キャッシュの先頭へ保存します。`uv run python scripts/check_firmware_endpoints.py` で実際のC処理の選択・保存を検証できます。

### テザリングなど、直接接続できない回線

DERPは異なるリージョン間を転送しません。端末は自分の待受用DERP接続を維持しつつ、設定済み会話サーバー（priority peer）のDERPリージョンへ送信用TLS接続を開きます。相手のリージョンは管理サーバーから取得した情報に従い、不明なリージョンを既定のDallasへ読み替えません。ホストからの手動pingは不要になる設計です。

送信用接続は1本に限定し、他の端末へのバックグラウンド探索で切り替わらないようにしています。汎用の全peer向け複数リージョン接続は対象外です。TLS接続失敗時はメモリを解放し、10秒以上空けて再試行します。待受用接続が失敗しても送信用接続は試行します。

`uv run python scripts/check_firmware_relay.py` は実装のC関数で異なるリージョンへの送信、既存接続の保持、リージョン変更、失敗後の再試行を検証します。実機確認ではホストの自動pingを無効にし、テザリング接続で電源OFF/ON後にSTATUSが成功することを確認してください。

既存の `.deps/microlink` に旧DERPパッチが適用済みの場合は、そのディレクトリを別名へ退避してから `setup_microlink.sh` を実行してください。新しいパッチ一式の初回適用と再実行に対応します。

仕様参照: <https://github.com/tailscale/tailscale/blob/main/derp/README.md>

復旧処理のC関数は、依存セットアップ後に `uv run python scripts/check_firmware_recovery.py` で検証できます（ホストのCコンパイラが必要）。

## ソース配布

```bash
firmware/scripts/setup_microlink.sh
uv run python scripts/package_firmware.py
```

`dist/xangi-stopwatch-firmware-source.zip` にファームのソース・ビルド手順・本体LICENSE・MicroLink/WireGuard由来のライセンス全文を同梱します。ライセンス欠落時は生成を中止します。Wi-Fi・登録キーを含むローカル設定やビルド済みbinは含めません。

この配布物は利用者がビルドするソース版です。bin配布には、Arduinoコア等のライセンスと対応ソース・再リンク条件も含む別の配布確認が必要です。

## ボタン操作

マイク対応版はAで録音開始・再押下で送信、録音中のBで破棄します。録音上限30秒を超えると破棄します。返答待ち・再生中のBは本体で音声と待機音声を停止し、`conversation_stop`イベントでホストへ中断を通知します。受信中の音声は読み切って破棄し、停止後の遅着音声も再生しません。待機中のBは`character_next`イベントを送信し、ホストが次の保存キャラへ切り替えます。STATUSの`character_button`が対応の目印です。

Tailnet版0.4ではWi-Fiを初期設定含め5件保存し、選択後に再起動して接続します。TailscaleのNVS登録は維持します。接続失敗時の自動フォールバックはありません。操作とUSB復旧は[使い方](../docs/usage.md#wi-fiを切り替える)を参照してください。

### バッテリーと会話停止（0.5）

画面上部中央に電池残量の目安（%）と充電中表示を10秒ごとに更新します。20%以下はオレンジ色、取得できない場合は `--%` を表示します。残量はM5Unifiedの電圧からの推定値です。STATUSに `battery_percent`（取得不能時-1）と `battery_charging` を返します。

録音中のBは録音取消、返答待ち・読み上げ中のBは会話停止、待機中のBはキャラ切替です。停止によってキャラは変わりません。実行中の音声認識・モデル・音声合成リクエスト自体が即座に終了するとは限りませんが、その返答は破棄し、処理終了後に次の録音を受け付けます。会話停止には対応するホスト拡張も必要です。

`uv run python scripts/check_firmware_controls.py` で実装のボタン処理を検証できます。実機での残量・充電表示、音声停止の体感、次の録音への復帰は書き込み後に確認してください。

## 画面全体の回転

画面を約0.6秒長押しし、1本指で円弧を描いて回転します。指を離した時に角度をNVSへ保存します。アバター・字幕・電池・AI利用量・タスク・起動画面をまとめて回します。スワイプは表示の向きに合わせて判定します。追加の466×466・16bit PSRAMバッファを使い、確保できない場合は従来の表示・タップ・スワイプを維持します。回転操作による描画は最大20回/秒で、実際の滑らかさは音声再生・通信と合わせて実機確認が必要です。
