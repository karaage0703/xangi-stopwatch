"""StopWatch conversation and device settings."""

from .constants import MAX_VOLUME

SETTINGS_HTML = """<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>xangi-stopwatchの設定</title><style>
*{box-sizing:border-box}body{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,system-ui,sans-serif;background:#f7f6f3;color:#37352f;margin:0;padding:0}
main{width:calc(100% - 32px);max-width:560px;margin:24px auto;background:white;padding:24px;border:1px solid #e3e2df;border-radius:12px}
h1{font-size:24px;overflow-wrap:anywhere}h2{font-size:20px;margin-top:32px}label{display:block;margin-top:18px}
select,input{width:100%;font:inherit;padding:10px;margin-top:6px;min-height:44px}
button{padding:12px 24px;font:inherit;margin-top:20px;min-height:44px}p{line-height:1.7}
fieldset{margin-top:18px;border:1px solid #aaa;padding:12px}fieldset label{margin:0;display:flex;align-items:center;gap:8px;min-height:44px}input[type=checkbox]{width:20px;min-height:20px;height:20px;margin:0}output{font-variant-numeric:tabular-nums}.hint{color:#555;font-size:14px}img{width:100px;height:100px;border-radius:12px}
.bubble{max-height:20rem;overflow-y:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;border-radius:16px;background:#eef2f6;line-height:1.8}.bubble.user{background:#e4f3ec;margin-left:24px}.bubble.assistant{margin-right:24px}#status{min-height:1.7em}
.xangi-host-nav { display: flex; flex: 0 0 auto; align-items: center; padding: 8px 16px; background: #ffffff; border-bottom: 1px solid #d5dae2; }
.xangi-host-nav[hidden] { display: none; }
.xangi-home-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 44px; padding: 0 14px; border: 1px solid #aab4c3; border-radius: 8px; background: #ffffff; color: #243247; font: 600 14px/1.4 system-ui, sans-serif; text-decoration: none; white-space: nowrap; }
.xangi-home-button:hover { color: #17263c; background: #edf2f8; border-color: #74849a; text-decoration: none; }
.xangi-home-button:focus-visible { outline: 3px solid #2563eb; outline-offset: 3px; }
.xangi-home-button:active { background: #dce6f2; }
.xangi-home-button svg { width: 18px; height: 18px; flex-shrink: 0; }

</style><nav class="xangi-host-nav" id="xangiHostNav" aria-label="xangi共通ナビゲーション" hidden><a class="xangi-home-button" id="xangiHomeLink" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg><span>xangiホーム</span></a></nav><main><h1>xangi-stopwatch</h1>
<p>本体のボタンで会話します。設定はxangi-stopwatch専用に保存されます。</p>
<section aria-label="会話の表示"><h2>会話</h2><p id="conversationState" role="status">接続を確認しています…</p><p class="hint">自分の認識結果</p><div id="transcript" class="bubble user">まだ会話がありません</div><p class="hint">返答</p><div id="reply" class="bubble assistant">ここに返答が表示されます</div></section>
<form id="conversation"><h2>キャラ設定</h2>
<p class="hint">① キャラを選ぶ → ② そのキャラのAgent・声・顔を変更 → ③「このキャラを保存」。別のキャラを作るときは「複製して追加」を押します。</p>
<label for="character">使用・編集するキャラ</label><select id="character" disabled></select>
<button id="duplicateCharacter" type="button" disabled>複製して追加</button>
<button id="deleteCharacter" type="button" disabled>削除</button>
<p id="editingCharacter" role="status"></p>
<p class="hint">キャラを選ぶと本体も切り替わります。切り替える前に編集内容を保存してください。</p>
<label for="characterName">キャラ名</label><input id="characterName" required maxlength="40">

<p class="hint">Aで録音、もう一度Aで送信。Bで次のキャラへ。録音中のBは取消です。</p>
<label for="agent">このキャラで会話するAgent</label><select id="agent" required><option value="">読み込み中…</option></select>
<p class="hint">xangi本体に登録したAgentから選びます。キャラごとに別のAgentを保存できます。同じAgentを複数のキャラで使うこともできます。顔は選択したAgentのワークスペースから自動で読み込みます。</p>
<label for="language">言語</label><select id="language"><option value="ja-JP">日本語</option><option value="en-US">英語</option><option value="zh-CN">中国語</option><option value="es-ES">スペイン語</option><option value="fr-FR">フランス語</option><option value="pt-BR">ポルトガル語</option></select>
<label for="provider">読み上げ</label><select id="provider"><option value="voicevox">VOICEVOX</option><option value="piper">Piper</option></select>
<label for="speaker">VOICEVOXの声</label><select id="speaker"></select><p class="hint" id="voiceHint"></p>
<button id="voiceTest" type="button">音声テスト</button><p class="hint">選択中の声を、この設定画面を開いた端末で再生します。設定の保存は不要です。</p><p id="testStatus" role="status"></p><button id="stopTest" type="button" hidden>テスト音声を停止</button>
<label for="imageClosed">待機画像（ワークスペース相対パス）</label><input id="imageClosed" required placeholder="assets/xangi-avatar/closed.png">
<label for="imageOpen">口開き画像（ワークスペース相対パス）</label><input id="imageOpen" required placeholder="assets/xangi-avatar/open.png">
<p class="hint">選択したAgentのワークスペースからの相対パスを入力してください。画像を読み込めない場合は、両方とも標準のxangiアバターを使います。</p>
<button id="checkImages" type="button">画像を確認</button><p id="imageStatus" role="status"></p>
<p><img id="previewClosed" alt="待機画像" hidden> <img id="previewOpen" alt="口開き画像" hidden></p>
<p class="hint">音声認識は共通のWhisperを使います。</p>
<button id="saveConversation" disabled>このキャラを保存</button><p id="characterStatus" role="status" aria-live="polite"></p></form>
<form id="volumeForm"><h2>音量</h2><label for="volume">音量 <output id="value">—</output> / __MAX_VOLUME__</label>
<input id="volume" type="range" min="0" max="__MAX_VOLUME__" value="0" disabled><button id="saveVolume" disabled>音量を保存</button></form>
<form id="displayForm"><h2>本体の表示</h2><label for="batteryPosition">電池表示の位置</label>
<select id="batteryPosition" disabled><option value="right">右上</option><option value="left">左上</option><option value="center">上中央</option><option value="hidden">非表示</option></select>
<button id="saveDisplay" disabled>表示位置を保存</button><p id="displayStatus" role="status"></p>
<p class="hint">本体画面をタップすると、操作案内・電池と充電表示を表示・非表示に切り替えます。会話のセリフは非表示にしても残ります。</p></form>
<form id="dashboardForm"><h2>利用量・タスク画面</h2>
<p class="hint">本体で左右にスワイプすると、アバター → 利用量 → タスクを切り替えます。上下スワイプで枠や一覧の次ページを表示します。</p>
<label for="usageMode">利用量の表示</label><select id="usageMode" disabled><option value="single">水面（1枠ずつ）</option><option value="multiple">複数バックエンドの横バー</option></select>
<label for="usageBackend">表示するバックエンド</label><select id="usageBackend" disabled><option value="default">xangiのデフォルトに追従</option><option value="selected">複数のバックエンドを選択</option><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="github-copilot">GitHub Copilot</option><option value="antigravity">Antigravity</option></select>
<fieldset id="usageBackends" hidden disabled><legend>表示するバックエンド（複数選択）</legend>
<label><input type="checkbox" value="codex"> Codex</label><label><input type="checkbox" value="claude-code"> Claude Code</label><label><input type="checkbox" value="github-copilot"> GitHub Copilot</label><label><input type="checkbox" value="antigravity"> Antigravity</label></fieldset>
<p class="hint">表示対象だけを変更します。会話に使うバックエンドは変わりません。黄色の線はモニターと同じ時間経過の目安です。複数選択ではチェックしたバックエンドを表示します。水面表示は上下スワイプで選択したバックエンドの各利用枠を切り替えます。目安の計算に必要な期間が取得できない場合は「未取得」と表示します。</p>
<p id="usageCurrent" role="status"></p><button id="saveDashboard" disabled>利用量の表示を保存</button><p id="dashboardStatus" role="status" aria-live="polite"></p></form>
<section aria-label="Wi-Fi設定"><h2>Wi-Fi</h2>
<p><strong>2.4GHzのみ対応（5GHzのWi-Fiには接続できません）。</strong></p>
<p class="hint">iPhoneのテザリングは「設定 → インターネット共有 → 互換性を優先」をONにしてください。携帯回線の5Gは利用できます。</p>
<p class="hint">テザリングも普段のWi-Fiも、同じTailscaleで接続します。切替先につながらなくても元のWi-Fiには戻りません。</p>
<p id="networkStatus" role="status">接続を確認しています…</p>
<label for="wifiProfile">保存したWi-Fi</label><select id="wifiProfile" disabled></select>
<button id="selectWifi" type="button" disabled>このWi-Fiに切り替える</button><button id="deleteWifi" type="button" disabled>削除</button>
<button id="refreshWifi" type="button">接続を確認</button>
<form id="wifiForm"><label for="wifiSSID">追加するSSID（2.4GHz）</label><input id="wifiSSID" required autocomplete="off">
<label for="wifiPassword">Wi-Fiパスワード</label><input id="wifiPassword" type="password" autocomplete="new-password" maxlength="63">
<p class="hint">認証なしのWi-Fiは空欄。パスワードは本体に保存し、画面へ読み戻しません。追加しただけでは接続先は変わりません。初期Wi-Fiを含め5件まで保存できます。</p>
<button id="addWifi" disabled>Wi-Fiを追加</button></form></section>
<p id="status" role="status" aria-live="polite">読み込んでいます…</p></main><script>
document.getElementById("xangiHostNav").hidden = !location.pathname.startsWith("/api/extensions/xangi-stopwatch/ui");
const $=id=>document.getElementById(id),status=$('status');
async function request(path,body){const r=await fetch(new URL('api/'+path,document.baseURI),body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'設定を保存できませんでした');return d;}
function option(select,value,text){const node=document.createElement('option');node.value=value;node.textContent=text;select.append(node);}
$('usageMode').onchange=()=>{const multi=$('usageMode').value==='multiple';$('usageBackend').disabled=multi;const selected=multi||$('usageBackend').value==='selected';$('usageBackends').hidden=!selected;$('usageBackends').disabled=!selected;};
$('usageBackend').onchange=$('usageMode').onchange;
(async()=>{try{const d=await request('display');$('usageMode').value=d.mode;$('usageBackend').value=d.backend;for(const box of $('usageBackends').querySelectorAll('input'))box.checked=(d.backends||['codex','claude-code','github-copilot','antigravity']).includes(box.value);$('usageMode').disabled=false;$('usageMode').onchange();$('saveDashboard').disabled=false;$('usageCurrent').textContent='現在の表示対象：'+(d.snapshot?.backend||'取得待ち');}catch(e){$('dashboardStatus').textContent=e.message;}})();
$('dashboardForm').onsubmit=async e=>{e.preventDefault();$('saveDashboard').disabled=true;try{await request('display',{mode:$('usageMode').value,backend:$('usageBackend').value,backends:[...$('usageBackends').querySelectorAll('input:checked')].map(box=>box.value)});$('dashboardStatus').textContent='表示設定を保存しました。本体の次回更新で反映します。';}catch(e){$('dashboardStatus').textContent=e.message;}finally{$('saveDashboard').disabled=false;}};
let wifiData=null;
function wifiButtons(){const profile=wifiData?.profiles.find(p=>p.id===Number($('wifiProfile').value));$('selectWifi').disabled=!profile;$('deleteWifi').disabled=!profile||profile.built_in||profile.id===wifiData.active;}
async function loadWifi(){try{wifiData=await request('network');$('wifiProfile').replaceChildren();for(const p of wifiData.profiles)option($('wifiProfile'),p.id,p.ssid+(p.id===wifiData.active?'（接続先）':''));$('wifiProfile').value=wifiData.active;$('wifiProfile').disabled=false;$('addWifi').disabled=wifiData.profiles.length>=5;wifiButtons();$('networkStatus').textContent='Wi-Fiを選択できます。';}catch(e){$('wifiProfile').disabled=true;$('selectWifi').disabled=true;$('deleteWifi').disabled=true;$('addWifi').disabled=true;$('networkStatus').textContent=e.message;}}
$('wifiProfile').onchange=wifiButtons;$('refreshWifi').onclick=loadWifi;
$('wifiForm').onsubmit=async e=>{e.preventDefault();$('addWifi').disabled=true;try{await request('network',{action:'add',ssid:$('wifiSSID').value,password:$('wifiPassword').value});$('wifiPassword').value='';$('wifiSSID').value='';await loadWifi();$('networkStatus').textContent='Wi-Fiを追加しました。選択して切り替えられます。';}catch(e){$('wifiPassword').value='';$('networkStatus').textContent=e.message;$('addWifi').disabled=false;}};
$('deleteWifi').onclick=async()=>{try{await request('network',{action:'delete',id:Number($('wifiProfile').value)});await loadWifi();}catch(e){$('networkStatus').textContent=e.message;}};
$('selectWifi').onclick=async()=>{if(!confirm('本体を再起動してWi-Fiを切り替えます。接続に失敗しても元に戻りません。続けますか？'))return;$('selectWifi').disabled=true;try{await request('network',{action:'select',id:Number($('wifiProfile').value)});$('networkStatus').textContent='切替を受け付けました。再接続後に「接続を確認」を押してください。接続できない場合はUSBで設定し直してください。';$('wifiProfile').disabled=true;$('deleteWifi').disabled=true;$('addWifi').disabled=true;}catch(e){$('networkStatus').textContent=e.message;$('selectWifi').disabled=false;}};
loadWifi();
$('provider').onchange=()=>{$('speaker').disabled=$('provider').value!=='voicevox';};
async function checkImages(){try{const d=await request('preview',{agent_id:$('agent').value,image_closed:$('imageClosed').value,image_open:$('imageOpen').value});for(const name of ['Closed','Open']){$('preview'+name).src='data:image/jpeg;base64,'+d[name.toLowerCase()];$('preview'+name).hidden=false;}$('imageStatus').textContent=d.fallback?'指定画像を読み込めないため、両方とも標準のxangiアバターを表示しています。':'指定した両方の画像を読み込めました。';}catch(e){$('previewClosed').hidden=true;$('previewOpen').hidden=true;$('imageStatus').textContent=e.message;}}
$('checkImages').onclick=checkImages;$('agent').onchange=checkImages;
let testContext=null,testSource=null,testGeneration=0;
function stopTest(){testGeneration++;if(testSource){testSource.stop();testSource=null;}$('stopTest').hidden=true;$('voiceTest').disabled=false;}
$('stopTest').onclick=()=>{stopTest();$('testStatus').textContent='停止しました。';};
$('voiceTest').onclick=async()=>{
 stopTest();const generation=testGeneration;$('voiceTest').disabled=true;$('stopTest').hidden=false;$('testStatus').textContent='音声を準備しています…';
 try{
  const AudioContextClass=window.AudioContext||window.webkitAudioContext;
  if(!AudioContextClass)throw Error('このブラウザは音声テストに対応していません。');
  if(!testContext)testContext=new AudioContextClass();
  await testContext.resume();
  const d=await request('voice-test',{provider:$('provider').value,speaker:Number($('speaker').value),language:$('language').value});
  if(generation!==testGeneration)return;
  const bytes=Uint8Array.from(atob(d.wav),c=>c.charCodeAt(0));
  const buffer=await testContext.decodeAudioData(bytes.buffer);
  if(generation!==testGeneration)return;
  const source=testContext.createBufferSource(),gain=testContext.createGain();
  source.buffer=buffer;gain.gain.value=0.15;source.connect(gain);gain.connect(testContext.destination);testSource=source;
  source.onended=()=>{source.disconnect();gain.disconnect();if(generation===testGeneration){testSource=null;$('stopTest').hidden=true;$('voiceTest').disabled=false;$('testStatus').textContent='音声テストが終了しました。';}};
  source.start();$('testStatus').textContent='再生中…';
 }catch(e){if(generation===testGeneration){stopTest();$('testStatus').textContent=e.message;}}
};
window.addEventListener('pagehide',()=>{stopTest();if(testContext){testContext.close();testContext=null;}});


let activeCharacter=null;
function applyCharacter(c){
 activeCharacter=c.active_character;$('character').replaceChildren();for(const item of c.characters)option($('character'),item.id,item.name);$('character').value=c.active_character;
 $('characterName').value=c.name;$('editingCharacter').textContent='編集中のキャラ：'+c.name;$('characterStatus').textContent='このキャラの設定を表示しています。変更後は保存してください。';
 if(![...$('agent').options].some(o=>o.value===c.agent_id))option($('agent'),c.agent_id,'現在のAgent（一覧にありません）');
 $('agent').value=c.agent_id;for(const id of ['provider','language'])$(id).value=c[id];
 if(![...$('speaker').options].some(o=>Number(o.value)===c.speaker))option($('speaker'),c.speaker,'声ID '+c.speaker);
 $('speaker').value=c.speaker;$('provider').onchange();$('imageClosed').value=c.image_closed;$('imageOpen').value=c.image_open;checkImages();
 $('character').disabled=false;$('duplicateCharacter').disabled=c.characters.length>=20;$('deleteCharacter').disabled=c.characters.length<=1;$('saveConversation').disabled=false;
}
async function characterAction(action){
 const id=$('character').value;
 try{applyCharacter(await request('characters',{action,id}));$('characterStatus').textContent='キャラを切り替えました。Agent・声・顔を変更して保存できます。';}
 catch(e){$('character').value=activeCharacter;$('characterStatus').textContent=e.message;}
}
$('character').onchange=()=>characterAction('select');
$('duplicateCharacter').onclick=()=>characterAction('duplicate');
$('deleteCharacter').onclick=()=>{if(confirm('選択中のキャラを削除しますか？'))characterAction('delete');};
(async()=>{try{const [c,a]=await Promise.all([request('config'),request('agents')]);$('agent').replaceChildren();for(const agent of a.agents)option($('agent'),agent.id,agent.id==='xangi:default'?'デフォルト':(agent.name||agent.id));
try{const v=await request('speakers');for(const s of v.speakers)option($('speaker'),s.id,s.name);}catch(e){$('voiceHint').textContent='声一覧を取得できません。現在の設定を維持します。';}
applyCharacter(c);status.textContent='キャラ設定を変更できます。';
}catch(e){status.textContent=e.message;}})();
let volumeLoaded=false,displayLoaded=false;
const states={idle:'Aで録音できます',recording:'録音中：Aで送信・Bで停止',transcribing:'音声を認識しています…',thinking:'返答を考えています…',speaking:'返答を読み上げています',unavailable:'会話を準備できません',connecting:'接続しています…',disconnected:'接続待ち',error:'会話エラー'};
async function refreshConversation(){try{if(document.hidden)return;const d=await request('settings');if(activeCharacter&&d.activeCharacter&&d.activeCharacter!==activeCharacter)applyCharacter(await request('config'));if(!displayLoaded&&d.batteryPosition){$('batteryPosition').value=d.batteryPosition;$('batteryPosition').disabled=false;$('saveDisplay').disabled=false;displayLoaded=true;}if(!volumeLoaded){$('volume').value=d.volume;$('value').textContent=d.volume;$('volume').disabled=false;$('saveVolume').disabled=false;volumeLoaded=true;}$('conversationState').textContent=d.conversationError||states[d.conversation]||d.conversation;$('transcript').textContent=d.transcript||'まだ認識結果がありません';$('reply').textContent=d.reply||'ここに返答が表示されます';}catch{$('conversationState').textContent='StopWatchに接続できません。再接続を待っています。';}finally{setTimeout(refreshConversation,2000);}}refreshConversation();
$('volume').oninput=()=>$('value').textContent=$('volume').value;
$('conversation').onsubmit=async e=>{e.preventDefault();$('saveConversation').disabled=true;try{applyCharacter(await request('config',{name:$('characterName').value,agent_id:$('agent').value,provider:$('provider').value,speaker:Number($('speaker').value),language:$('language').value,image_closed:$('imageClosed').value,image_open:$('imageOpen').value}));$('characterStatus').textContent='「'+$('characterName').value+'」のAgent・声・顔を保存しました。';}catch(e){$('characterStatus').textContent=e.message;}finally{$('saveConversation').disabled=false;}};
$('volumeForm').onsubmit=async e=>{e.preventDefault();$('saveVolume').disabled=true;try{await request('settings',{volume:Number($('volume').value)});status.textContent='音量を保存しました。';}catch(e){status.textContent=e.message;}finally{$('saveVolume').disabled=false;}};
$('displayForm').onsubmit=async e=>{e.preventDefault();$('saveDisplay').disabled=true;try{await request('settings',{batteryPosition:$('batteryPosition').value});$('displayStatus').textContent='表示位置を保存しました。';}catch(e){$('displayStatus').textContent=e.message;}finally{$('saveDisplay').disabled=false;}};
</script></html>""".replace("__MAX_VOLUME__", str(MAX_VOLUME))
