# StopWatch dashboard

466×466の丸画面で、会話の顔・AI利用量・タスクを左右スワイプで巡回する。
利用量の目安はxangi Monitorの usagePacePercent と同じ計算を使う。

- 濃紺背景、シアンの使用量、黄色の目安線、白い本文。色だけに頼らず数値と状態名を併記。
- 単独表示は全画面の水面。中央に使用率、目安、枠名、リセットまでの時間。
- 複数表示は3行の横バー。タスクも3行で、状態と現在の作業を示す。
- 左右60px以上で画面を移動、上下で枠・一覧のページを移動。斜め・短いドラッグでは切り替えない。
- アバターのタップは電池・操作案内のみ切替、セリフは常に表示。録音と停止ボタンは維持。スワイプをタップとして処理しない。
- 本体の画面切替はネットワーク応答を待たない。ホスト更新断20秒で前回値と表示。
- 項目なし・未取得・更新失敗を区別。欠けた利用量・目安を0%にしない。
- 設定画面は既存フォームの書体・配色を継承。ラベル、disabled、保存結果を明示。

実装: firmware/examples/stopwatch/main/dashboard.h、navigation.h、src/xangi_stopwatch/ui.py。
`uv run python scripts/render_dashboard_preview.py` は実際のファーム描画コードをデスクトップ用canvasで実行する。
生成SVGはサンプルデータであり、フォント計測は近似。実機の滑らかさ・タッチ感度の代用にはしない。

品質確認に参照: https://raw.githubusercontent.com/Nutlope/hallmark/main/skills/hallmark/SKILL.md
フォーム状態の参照: https://design.digital.go.jp/dads/

設定画面の左上にはxangi-searchと共通の家アイコン・44px高の「xangiホーム」ボタンを置く。同じoriginの`/`へ戻り、直接アクセス時は非表示。名称は`xangi-stopwatch`に統一する。
