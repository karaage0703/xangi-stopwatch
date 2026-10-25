# USB Wi-Fi設定の検証

既存画面の色・文字・余白を維持し、初回登録と復旧を同じフォームにまとめる。必須入力・エラー理由を文章で示し、フォーカスと状態通知を保つ。参照: [DADSフォームの使い方](https://design.digital.go.jp/dads/components/input-text/usage/)、[アクセシビリティ](https://design.digital.go.jp/dads/components/input-text/accessibility/)。Web Serialの読取・切断処理は[Chrome公式仕様](https://developer.chrome.com/docs/capabilities/serial)に従う。

## ローカル検証

```bash
uv run pytest -q
uv run ruff check src tests scripts/check_firmware_wifi.py scripts/check_usb_wifi_ui.py
uv run python scripts/check_firmware_wifi.py
uv run --with playwright playwright install chromium
uv run --with playwright python scripts/check_usb_wifi_ui.py --output /tmp/stopwatch-usb-wifi-ui
firmware/scripts/setup_microlink.sh
pio run -d firmware -e stopwatch-main-tailnet
pio run -d firmware -e stopwatch-main
```

ブラウザ検証は実際のHTMLとReadableStream/WritableStreamを使い、USBデバイスだけを模擬する。未設定、初回登録、再起動後の接続確認、同一SSIDの修正、不正入力、保存上限、接続取消、旧ファーム、抜線、認証なしWi-Fiを検証する。1100pxと375pxで操作し、スクリーンショットと横はみ出しも確認する。ファーム検証は実際のC++関数を取り出し、NVS保存・USB応答だけを模擬する。

## 実機での残確認

- 初期SSIDが空のファームを専用StopWatchへ書き込み、USB設定からWi-Fi・Tailnet・会話サーバー接続まで進める。
- 誤パスワードからUSBで修正し、電源OFF/ON後も設定が残ることを確認する。
- Wi-Fi接続中のUSB状態確認で、会話イベントがUSBへ奪われないことを確認する。
- 既存NVSと既存tailnet_secrets.hを使った更新で、保存したWi-Fi・登録済みTailscaleが継続することを確認する。
- Mac/Windows/Linux実機でUSBポート選択、再起動後の再選択を確認する。

ビルド成功・模擬USBの成功だけでは、実機での初回接続・電源断耐性を確認済みとしない。
