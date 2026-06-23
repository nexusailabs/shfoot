# KIRO + AgentCore 현장 치트시트 (6/24) — 버벅대지 않기 위한 단 한 장

> 오늘(6/23) 패인 절반 = 현장에서 메커니즘 처음 배우다 시간 날림. 이 문서의 목적: **Kiro/배포를 6/24에 처음 보지 않게** 한다.
> 표기: `[VERIFIED]` 공식문서 확인 / `[ASSUMPTION]` 현장 첫 30분에 확인.

## 0. 단 하나만 기억해라
**Kiro ≈ VS Code(Code OSS 포크) + 사이드바에 AI 에이전트.** 운영감각은 Claude Code와 비슷하다(동일하다는 보장은 아님 — 단축키/메뉴는 다를 수 있음).
메뉴 못 외워도 된다 — **오른쪽 채팅창에 한국어로 시키면 걔가 파일 고치고 터미널 돌린다.** `[VERIFIED: Kiro = agentic IDE w/ chat, kiro.dev] [ASSUMPTION: "Claude Code와 동일"은 단순화]`
그리고 **우리 키트는 순수 Python이라 Kiro 없이 그냥 터미널로도 된다.** Kiro는 편해서 쓰는 거지 필수 아님.

## 1. 안 버벅대는 작업 루프 (현장 내내 이 4줄만 반복)
1. **포털 obs 1개 복사** → 터미널: `pbpaste | python reconcile.py -` → GREEN 뜰 때까지 `state_from_obs` 고침
2. **숫자 튜닝**: Kiro 채팅에 "policy.py에서 `<튜너블>`을 `<값>`으로 바꿔" (또는 직접 편집)
3. **검증**: `python -m unittest test_policy` → green 확인
4. **배포**: `agentcore deploy` (아래 3번) — ⚠️ **단, §4 항목①(제출방식: CLI vs 포털)을 현장에서 확인한 뒤에만.** 확인 전엔 배포 경로 가정 금지(= 6/23 함정).
→ 1차 매치 관찰 → 2번으로. 끝. 새 메커니즘 배울 거 없음.

## 2. Kiro 켜고 폴더 열기 (3클릭)
- Kiro 실행 → 로그인 (Builder ID / Google / GitHub 중 아무거나, AWS 계정 필수 아님) `[VERIFIED]`
- `File > Open Folder` → `~/football-cup`
- 하단 터미널 열기: **Ctrl+`** (백틱) → `source .venv/bin/activate`
- 막히면: 오른쪽 채팅에 **"이 폴더 열고 .venv 활성화해줘"** 라고 시켜라. 그게 Kiro의 존재 이유다.

## 3. AgentCore 배포 = 터미널 명령 (GUI 클릭 아님) `[ASSUMPTION: 아래 정확한 플래그/하위명령은 docs 기반 — 현장 CLI로 확인]`
> CLI 자체와 "터미널 배포" 흐름은 공식문서 확인됨. 단 `configure -e` / `--disable-memory` / `dev` / `invoke` / "CodeZip·Docker 불필요"의 **정확한 철자·옵션은 버전마다 다를 수 있다** → 현장에서 `agentcore --help`로 한 번 확인 후 사용.
표준 흐름 (현장에서 정확한 엔트리포인트 파일명만 맞추면 됨):
```bash
# 1) 한 번만: 에이전트 설정 (entrypoint = 런타임이 부르는 파일)
agentcore configure -e squad.py            # 메모리 불필요시 --disable-memory
# 2) 배포 (S3 CodeZip, Docker 불필요)
agentcore deploy
# 3) 로컬 점검 (핫리로드 + inspector) — 배포 전 테스트
agentcore dev
# 4) 호출 테스트
agentcore invoke '{"role":"FWD","obs":{...}}'
```
- 설정은 `.bedrock_agentcore.yaml`에 저장됨. `agentcore validate`로 스키마 오류 사전 점검.
- **막히면 Kiro 채팅에**: "agentcore로 squad.py를 Runtime에 배포해줘" → 걔가 명령 만들어 돌림.

## 4. ★ 현장 첫 30분에 반드시 확인 (ASSUMPTION 닫기) ★
오늘처럼 "내가 가정한 배포법 ≠ 실제"면 또 막힌다. 워크숍 자료/멘토에게 **이 4개부터** 물어라:
1. **제출 방식**: `agentcore deploy`로 Runtime에 올리나, 아니면 **Player Portal에 코드/Agent 업로드**인가? `[ASSUMPTION]`
2. **런타임이 우리 5 Agent를 매 틱 어떻게 호출**하고 액션을 어떻게 읽나? → `state_from_obs`/`action_to_runtime` 모양 확정
3. **관측 dict 정확한 키 이름 + 좌표계** (x 어느 쪽이 상대 골대?) → `reconcile.py`로 즉시 검증
4. **툴 안에서 외부 API 호출 허용 여부** (실격 룰)

영어로 물을 문장:
- *"How exactly do we submit our agents — the AgentCore CLI, or upload to a player portal?"*
- *"What exact field names does the per-tick observation use, and which x is the opponent's goal?"*
- *"Are external API calls inside an agent's tools allowed, or disqualifying?"*

## 5. 막혔을 때 30초 안에 푸는 법 (우선순위)
1. **Kiro 채팅(Claude)에 그대로 한국어로 물어라** — 현장 자료 첨부해서. 너의 Claude Code랑 동일.
2. 그래도 안 되면 **나(사이드 Claude)한테** 화면/에러 붙여넣기.
3. Kiro 자체가 말썽이면 **버려라** — 그냥 터미널 + venv로 `python reconcile.py`, 파일 직접 편집, `agentcore deploy`. 키트가 순수 Python이라 에디터 무관.

**한 줄:** Kiro는 "Claude 들어있는 VS Code"다. 못 외운 메뉴는 채팅에 시켜라. 배포는 `agentcore deploy` 한 줄. 그게 전부다.

---
**Sources:** kiro.dev · aws.amazon.com/documentation-overview/kiro · docs.aws.amazon.com/bedrock-agentcore (CLI get-started) · strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore
