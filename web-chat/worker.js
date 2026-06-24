const HTML = `<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>풋볼컵 현장 · 6/24</title>
<style>
  :root{--bg:#0b0f14;--panel:#131a22;--panel2:#0f1620;--line:#243240;--ink:#e8eef5;--mut:#8aa0b4;--acc:#37d67a;--acc2:#ffcf4a;--warn:#ff6b6b;--mono:ui-monospace,Menlo,monospace}
  *{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo",sans-serif}
  .tabs{position:sticky;top:0;z-index:9;display:flex;background:#0c1218;border-bottom:1px solid var(--line)}
  .tabs button{flex:1;background:none;border:none;color:var(--mut);font-size:15px;font-weight:800;padding:13px;cursor:pointer;border-bottom:2px solid transparent}
  .tabs button.on{color:var(--acc);border-bottom-color:var(--acc)}
  .wrap{max-width:760px;margin:0 auto;padding:16px}
  h1{font-size:20px;margin:0 0 2px}.sub{color:var(--mut);font-size:13px;margin-bottom:8px}
  h2{font-size:16px;margin:22px 0 8px;color:var(--acc)}h2 .n{color:var(--mut);margin-right:6px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 15px;margin:9px 0}
  ol,ul{margin:5px 0;padding-left:20px}li{margin:5px 0}b{color:#fff}
  .tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:6px;background:#16321f;color:var(--acc);border:1px solid #1f4a30}
  .tag.w{background:#2a1416;color:var(--warn);border-color:#4a1f22}
  code{font-family:var(--mono);font-size:13px;background:var(--panel2);border:1px solid var(--line);border-radius:5px;padding:1px 6px}
  pre{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:11px;overflow:auto;font-family:var(--mono);font-size:13px}
  .url{color:var(--acc2);font-family:var(--mono);word-break:break-all}
  .lead{background:linear-gradient(180deg,#16212c,#101820);border:1px solid var(--line);border-radius:12px;padding:13px 15px}.lead b{color:var(--acc)}
  .cmd{display:flex;gap:8px;background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin:6px 0}
  .cmd p{margin:0;flex:1;font-family:var(--mono);font-size:13px;color:#dbe7f0}
  .cmd button{background:#1a2531;color:var(--acc);border:1px solid #284a39;border-radius:7px;padding:4px 9px;font-size:12px;font-weight:700;cursor:pointer}
  .grp{margin:12px 0 3px;font-size:13px;font-weight:800;color:var(--acc2)}.grp.crit{color:var(--warn)}
  .pill{font-size:12px;color:var(--mut)}
  #chat{display:none;flex-direction:column;height:calc(100vh - 49px)}
  #log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
  .msg{max-width:88%;padding:9px 12px;border-radius:13px;white-space:pre-wrap;word-break:break-word;font-size:14.5px;line-height:1.55}
  .msg.user{align-self:flex-end;background:#1f3a2a;border:1px solid #2c5740}
  .msg.assistant{align-self:flex-start;background:var(--panel);border:1px solid var(--line)}
  .msg .who{font-size:11px;color:var(--mut);font-weight:700;margin-bottom:2px}
  .msg img{max-width:100%;border-radius:9px;margin-top:6px;display:block}
  .prev{display:none;padding:8px 12px;border-top:1px solid var(--line);background:#0c1218}
  .prev img{height:54px;border-radius:7px;border:1px solid var(--line);vertical-align:middle}
  .prev button{margin-left:8px;background:#2a1416;color:var(--warn);border:1px solid #4a1f22;border-radius:6px;padding:3px 8px;font-size:12px;cursor:pointer}
  .bar{display:flex;gap:8px;align-items:flex-end;padding:10px;border-top:1px solid var(--line);background:#0c1218;padding-bottom:calc(10px + env(safe-area-inset-bottom))}
  .att{flex:0 0 auto;display:flex;align-items:center;justify-content:center;width:42px;height:42px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;font-size:19px;cursor:pointer}
  .bar textarea{flex:1;resize:none;background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:15px/1.4 inherit;max-height:120px}
  .bar .send{flex:0 0 auto;background:var(--acc);color:#04140a;border:none;border-radius:10px;padding:0 18px;height:42px;font-weight:800;font-size:15px;cursor:pointer}
  .hint{color:var(--mut);font-size:12px;text-align:center;padding:8px}
</style></head><body>
<div class="tabs"><button id="tCheat" class="on" onclick="tab('cheat')">치트</button><button id="tChat" onclick="tab('chat')">클로드 채팅</button></div>

<div id="cheat" class="wrap">
  <h1>⚽ 풋볼컵 현장 치트 <span class="pill">6/24 · 노코드</span></h1>
  <div class="sub">노트북은 그냥 브라우저. 코드 안 짬. 막히면 위 <b>클로드 채팅</b> 탭(캡쳐도 전송 가능).</div>
  <div class="lead"><b>큰 그림 (비유):</b> <b>빌드 포털 = 선수 만드는 공장</b>, <b>경기 포털 = 경기장</b>.<br>공장에서 AI 선수 5명 만들고 → 각자 명찰(ARN) 받아서 → 경기장에 그 명찰 5개 등록 → 연습 → 대전.<br>노트북은 두 사이트 여는 <b>브라우저일 뿐, 코드는 안 짠다.</b></div>

  <h2><span class="n">1</span>입장 (빌드 포털 열기)</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div>선수를 만드는 AWS 워크숍 사이트. 왼쪽 단계별 목차가 <b>"정답지"</b> — 명령어가 거기 다 적혀있으니 그대로 복붙하면 됨.
    <div class="grp">할 일</div>
    <ol>
      <li>바탕화면 브라우저 바로가기 실행</li>
      <li>주소창에 <span class="url">catalog.workshops.aws/join</span></li>
      <li>현장에서 받은 <b>Event access code</b> 입력 → 로그인</li>
      <li>화면 우측 상단 <b>리전이 us-east-1</b>인지 확인 (아니면 클릭해서 바꿈)</li>
    </ol>
    <div class="grp">주의</div>access code는 현장에서 나눠줌(스크린/안내데스크). 못 찾으면 멘토에게 "Event access code?"
  </div>

  <h2><span class="n">2</span>CloudShell 열기 (검은 명령창)</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div><b>브라우저 안에서 도는 리눅스 터미널.</b> 내 노트북엔 아무것도 설치 안 함. 윈도우든 상관없는 이유가 이거.
    <div class="grp">할 일</div>
    <ol>
      <li>AWS 콘솔 상단 <b>검색창</b>에 <code>CloudShell</code> 입력 → 클릭</li>
      <li>검은 창 뜰 때까지 10~20초 대기</li>
      <li><code>[cloudshell-user@...]$</code> 프롬프트 보이면 준비 완료</li>
    </ol>
    <div class="grp">팁</div>워크숍에서 "Local Machine / Harness / CloudShell" 중 고르라 하면 → <b>CloudShell</b> 선택(환경문제 없음). 붙여넣기는 우클릭 또는 Ctrl+Shift+V.
  </div>

  <h2><span class="n">3</span>샘플 코드 받기 (클론)</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div>주최측이 준 <b>기본 축구팀 코드.</b> 우리는 이걸 토대로 프롬프트·숫자만 바꿈.
    <div class="grp">할 일</div>워크숍 <b>"단계1: 저장소 클론"</b>에 적힌 4줄 명령 복사 → CloudShell에 붙여넣고 Enter. 다운로드 로그 뜨고 폴더 생기면 성공.
    <div class="grp">우리 키트도 같이</div>같은 창에서 한 줄 더:
    <pre>git clone https://github.com/nexusailabs/shfoot</pre>
    그럼 우리 프롬프트·정책이 옆 폴더에 생김.
  </div>

  <h2><span class="n">4</span>선수 5명 배포 (5+2 명령)</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div>선수 5명을 클라우드에 실제로 띄우는 작업. <b>"7(5+2)" = 선수 5 + 도구/게이트웨이 2.</b>
    <div class="grp">할 일</div>워크숍 <b>"3단계 … AgentCore Gateway"</b>의 배포 명령을 CloudShell에 붙여넣고 Enter → <b>람다 + 게이트웨이 자동 생성.</b>
    <div class="grp">보이는 것</div>생성 로그가 주르륵. 끝나면 선수별 <b>ARN(주소)</b> 이 출력되거나 콘솔에서 확인 가능.
  </div>

  <h2><span class="n">5</span>하네스로 선수 완성 + 프롬프트 주입 ★승부처</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div><b>하네스 = 각 선수에게 "성격(프롬프트)"과 "두뇌(모델)"를 붙이는 노코드 화면.</b>
    <div class="grp">할 일</div>선수(GK·DEF·DEF·MID·FWD)마다:
    <ol>
      <li><b>우리 역할 프롬프트 붙여넣기</b> — 채팅 탭에서 "GK 프롬프트 줘" 라고 하면 내가 바로 줌</li>
      <li><b>모델 선택</b> — 가벼운 모델 기본(빠름), 무거운 건 여유 있을 때만</li>
    </ol>
    <div class="grp crit">왜 승부처냐</div>5명이 다 공 쫓으면 <b>무조건 진다(뭉침).</b> 프롬프트에 "네 존 지켜, 공 쫓지 마"가 박혀야 함 — <b>우리 프롬프트가 그렇게 돼있음.</b> 이게 이기는 핵심.
  </div>

  <h2><span class="n">6</span>명찰(ARN) 5개 챙기기</h2>
  <div class="card">
    <div class="grp">이게 뭐냐</div><b>ARN = 각 선수의 고유 주소.</b> 경기장에 이 주소를 넣어야 그 선수가 출전. <code>arn:aws:...</code> 로 시작하는 긴 문자열.
    <div class="grp">할 일</div>하네스/콘솔에서 Agent 하나하나 상세 → <b>ARN 복사 → 5개 다 메모장에.</b> (어느 ARN이 GK/DEF/MID/FWD인지 표시해둬)
  </div>

  <h2><span class="n">7</span>경기 포털에 연결 → 연습 → 대전</h2>
  <div class="card">
    <ol>
      <li>새 탭 → <span class="url">agentic-football.aws.dev</span> → <b>Team Code</b> 입력 (빌드 코드 아님, 별도 경기 코드)</li>
      <li>우측 상단 언어 토글로 한/영 전환 가능</li>
      <li><b>"내 팀" 페이지의 5칸에 ARN 5개 붙여넣기</b> (자리=포지션 맞게)</li>
      <li><b>연습경기 먼저</b> — 선수들 정상 응답하는지 + 우리 팀 공격 방향(어느 골대) 확인. 뭉치면 알려줘 → 존 좌표 강제</li>
      <li>검증되면 <b>다른 팀에 도전</b></li>
    </ol>
  </div>

  <h2><span class="n">8</span>성적 올리기 (튜닝)</h2>
  <div class="card"><ul>
    <li><b>CloudWatch</b>: 경기 중 선수 결정 로그를 여기서 봄 = 왜 졌는지 디버깅</li>
    <li><b>모델</b>: 포지션별 다르게(사고깊이 vs 응답속도)</li>
    <li><b>숫자 튜닝</b>: 슛 강도·패스·압박 타이밍 <b>한 번에 하나씩</b> (여러 개 동시 ✗)</li>
    <li>막히는 화면은 <b>캡쳐해서 채팅 탭에 던져</b> — 보고 다음 한 수 줄게</li>
  </ul></div>

  <h2><span class="n">9</span>경기 중 영어 감독 지시 <span class="tag">라이브</span></h2>
  <div class="card">
    <div class="sub">사이드라인 자연어 지시 → <b>영어만, 구체적으로.</b> 눌러 복사.</div>
    <div class="grp">기본 (시작 시)</div>
    <div class="cmd"><p>Defenders, hold your zones. Do NOT chase the ball out of position.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Only the single nearest player presses the ball. Everyone else keeps formation.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Forward, stay on the last defender's line. Shoot on sight when in range.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Goalkeeper, stay on your line unless the ball enters the penalty box.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Midfielder, prioritize forward passes into open space, not sideways.</p><button onclick="cp(this)">복사</button></div>
    <div class="grp crit">뭉침 보일 때 ★</div>
    <div class="cmd"><p>STOP swarming the ball. Return to your assigned zones immediately.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Defenders, stop pushing forward. Recover to your defensive line now.</p><button onclick="cp(this)">복사</button></div>
    <div class="grp">지고 있을 때</div>
    <div class="cmd"><p>We are behind. Push the defensive line up and commit one extra player to attack.</p><button onclick="cp(this)">복사</button></div>
    <div class="grp">이기고 있을 때</div>
    <div class="cmd"><p>We are ahead. Drop deeper, keep possession, and run down the clock.</p><button onclick="cp(this)">복사</button></div>
    <div class="grp">상황별</div>
    <div class="cmd"><p>Opponent is attacking down the left. Shift the defensive line to cover that flank.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Stamina is low. Reduce pressing, hold compact shape, conserve energy.</p><button onclick="cp(this)">복사</button></div>
    <div class="cmd"><p>Too many turnovers. Play safer short passes and keep possession first.</p><button onclick="cp(this)">복사</button></div>
  </div>

  <h2><span class="n">10</span>첫 30분 체크</h2>
  <div class="card"><ul>
    <li>obs 키 이름 + 좌표계(x 어느쪽이 상대골대?) → reconcile</li>
    <li>스코어링 세부 / 툴 안 외부API 허용 여부(실격룰)</li>
  </ul></div>
  <div class="hint">repo: github.com/nexusailabs/shfoot</div>
</div>

<div id="chat">
  <div id="log"></div>
  <div id="prev" class="prev"></div>
  <div class="bar">
    <label class="att">📷<input id="file" type="file" accept="image/*" onchange="pick(this.files[0])" hidden></label>
    <textarea id="inp" rows="1" placeholder="질문 / 에러 / 캡쳐 붙여넣기(Ctrl+V)…"></textarea>
    <button class="send" onclick="send()">전송</button>
  </div>
</div>

<script>
function tab(t){
  var c=t==='cheat';
  document.getElementById('cheat').style.display=c?'block':'none';
  document.getElementById('chat').style.display=c?'none':'flex';
  document.getElementById('tCheat').className=c?'on':'';
  document.getElementById('tChat').className=c?'':'on';
  if(!c){poll();setTimeout(scrollDown,60);}
}
function cp(b){var t=b.parentElement.querySelector('p').innerText;navigator.clipboard.writeText(t).then(function(){var o=b.innerText;b.innerText='✓';setTimeout(function(){b.innerText=o;},900);});}
var seen=0, pendImg=null;
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function render(msgs){
  var log=document.getElementById('log');
  log.innerHTML=msgs.map(function(m){
    var im=m.img?'<img src="'+m.img+'">':'';
    return '<div class="msg '+m.role+'"><div class="who">'+(m.role==='user'?'나':'클로드')+'</div>'+esc(m.text)+im+'</div>';
  }).join('');
}
function scrollDown(){var l=document.getElementById('log');l.scrollTop=l.scrollHeight;}
function poll(){
  fetch('/api/poll').then(function(r){return r.json();}).then(function(d){
    var l=document.getElementById('log');
    var near=l.scrollHeight-l.scrollTop-l.clientHeight<90;
    if(d.length!==seen){render(d);seen=d.length;if(near)scrollDown();}
  }).catch(function(){});
}
// downscale image to keep payload small (longest side 1500, jpeg .72)
function shrink(file,cb){
  var img=new Image(), url=URL.createObjectURL(file);
  img.onload=function(){
    var w=img.width,h=img.height,M=1500;
    if(w>M||h>M){if(w>h){h=Math.round(h*M/w);w=M;}else{w=Math.round(w*M/h);h=M;}}
    var c=document.createElement('canvas');c.width=w;c.height=h;
    c.getContext('2d').drawImage(img,0,0,w,h);URL.revokeObjectURL(url);
    cb(c.toDataURL('image/jpeg',0.72));
  };
  img.src=url;
}
function pick(file){ if(!file)return; shrink(file,function(d){pendImg=d;showPrev();}); }
function showPrev(){
  var p=document.getElementById('prev');
  if(pendImg){p.style.display='block';p.innerHTML='<img src="'+pendImg+'"><button onclick="pendImg=null;showPrev()">✕ 캡쳐 제거</button>';}
  else{p.style.display='none';p.innerHTML='';}
}
function send(){
  var i=document.getElementById('inp');var t=i.value.trim();
  if(!t&&!pendImg)return;
  var img=pendImg; pendImg=null; showPrev();
  i.value='';i.style.height='auto';
  fetch('/api/send',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({text:t,img:img})}).then(function(){poll();});
  var l=document.getElementById('log');
  l.insertAdjacentHTML('beforeend','<div class="msg user"><div class="who">나</div>'+esc(t)+(img?'<img src="'+img+'">':'')+'</div>');scrollDown();
}
var inp=document.getElementById('inp');
inp.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,120)+'px';});
inp.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
inp.addEventListener('paste',function(e){
  var items=(e.clipboardData||{}).items||[];
  for(var k=0;k<items.length;k++){if(items[k].type.indexOf('image')===0){var f=items[k].getAsFile();if(f){pick(f);e.preventDefault();}}}
});
setInterval(function(){if(document.getElementById('chat').style.display!=='none')poll();},3000);
</script>
</body></html>`;

const json = (o, s) => new Response(JSON.stringify(o), { status: s || 200, headers: { "content-type": "application/json" } });

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    try {
      if (p === "/" || p === "") return new Response(HTML, { headers: { "content-type": "text/html;charset=utf-8" } });

      if (p === "/api/send" && req.method === "POST") {
        const { text, img } = await req.json();
        const tt = (text || "").toString().slice(0, 8000);
        const im = img ? img.toString().slice(0, 3000000) : null;   // ~2MB dataURL cap
        if (!tt.trim() && !im) return json({ error: "empty" }, 400);
        await env.DB.prepare("INSERT INTO msgs (role,text,ts,answered,img) VALUES ('user',?,?,0,?)")
          .bind(tt || "[캡쳐]", Date.now(), im).run();
        return json({ ok: true });
      }

      if (p === "/api/poll") {
        const { results } = await env.DB.prepare("SELECT id,role,text,img FROM msgs ORDER BY id ASC").all();
        return json(results || []);
      }

      if (p === "/api/pending") {
        if (url.searchParams.get("key") !== env.AGENT_KEY) return json({ error: "forbidden" }, 403);
        const { results } = await env.DB.prepare("SELECT id,text,img FROM msgs WHERE role='user' AND answered=0 ORDER BY id ASC").all();
        return json(results || []);
      }

      if (p === "/api/reply" && req.method === "POST") {
        const { replyTo, text, key } = await req.json();
        if (key !== env.AGENT_KEY) return json({ error: "forbidden" }, 403);
        await env.DB.prepare("INSERT INTO msgs (role,text,ts,answered) VALUES ('assistant',?,?,1)")
          .bind((text || "").toString().slice(0, 12000), Date.now()).run();
        if (replyTo) await env.DB.prepare("UPDATE msgs SET answered=1 WHERE id=?").bind(replyTo).run();
        return json({ ok: true });
      }

      return new Response("not found", { status: 404 });
    } catch (e) {
      return json({ error: String((e && e.message) || e) }, 500);
    }
  }
};
