# Agentic Football Cup — 우승 전략 (6/24, AI League 틀 전이)

> Source-of-truth for the 2026-06-24 AWS Summit Shanghai **Agentic Football Cup** (GO BUILD day, 13:00–17:30, bring-your-own-laptop).
> Built on the 6/23 AI League playbook (`~/ai-league/`). Tags: `[VERIFIED]` = confirmed from official sources / AI League live data; `[ASSUMPTION]` = standard-football-sim inference, **must be reconciled against on-site workshop materials in the first 30 min.**

---

## 0. 핵심 통찰 한 줄
AI League 패인 = *"stock pathfinder가 스파이크를 행진"*. **Football Cup 동일 함정 = "5개 에이전트가 전부 공을 쫓아 뭉친다"(ball-chasing swarm).**
둘 다 나이브 정책이 코드/프롬프트에 박혀 지는 것 — 이기는 법도 동일: **정책을 역할·코드에 명시적으로 박는다.**

## 1. 두 대회 매핑 (전이 원칙)

| AI League (6/23) | → | Football Cup (6/24) |
|---|---|---|
| 노코드 빌더 + 람다 | | **Strands Agents SDK 실코드** (더 코드-중심) `[VERIFIED]` |
| 1 supervisor + 5 sub-agent | | **5 자율 에이전트/팀** `[VERIFIED]` |
| 라우팅은 람다 코드 안 (프롬프트❌) | | **정책은 에이전트 코드/프롬프트 안** — 산문 아닌 구조가 승부 |
| 스파이크 회피 = 천장 돌파 | | **ball-chasing 회피(역할/존 규율)** = 천장 돌파 |
| terse 답 = 토큰 보너스 | | **terse 결정 = 2초 예산 안에 응답** `[VERIFIED: 2초 결정]` |
| Best Score 재제출 10~20회 | | 토너먼트 → 매치 간 config 튜닝 반복 |
| deploy-first (HK 패인=배포 지연) | | **점심 전 첫 매치까지 squad 배포 완료** `[VERIFIED]` |

## 2. 메커니즘  `[VERIFIED via agenticfootballcup.com/learnmore, 2026-06-18]`
- **포맷**: 반나절, 1 토너먼트. 빌드 → 점심 전 1차 매치 → 튜닝/툴 교체/협응 → 토너먼트 결승.
  (싱가포르 레퍼런스: 9:30 빌드 / 11:30 1차+점심 / 12:30 결승 / 13:00 시상)
- **인원**: 팀당 **자율 AI 에이전트 5** (한 팀에 사람 ~4: 개발자 + 옵션 비개발자). 5 vs 5.
- **관측 (full game state, 매 2초)**: **공 위치 + 전 선수 위치 + 스태미나 + 스코어.**
- **액션 = 정확히 11개**: `pass · shoot · dribble · press · mark · intercept · tackle · clear · move · support · hold`.
- **레이턴시 예산**: 각 에이전트는 **500ms 이내 결정 반환** (2초는 사이클, 반환 데드라인은 500ms). → 무거운 추론은 코드에 사전계산.
- **스택**: Amazon Bedrock + **AgentCore**(배포) + **Strands Agents SDK**(Python) + **Kiro IDE**(코드 작성). 모델 = **Nova / Claude / 아무 Bedrock 모델 자유선택.**
- **학습목표(=채점이 보는 역량)**: 멀티에이전트 협응·실시간 상태관리·tool use & structured output·guardrail & retry·observability·프롬프트 엔지니어링.
- **경로**: Day-of 토너먼트 → 완주=글로벌 리그 출전권 → 조 우승 → re:Invent 2026 LV 무대.
- **여전히 미공개** `[ASSUMPTION]`: 상태 dict의 **정확한 필드명·좌표계**, 스코어링 세부(골 외 가점 여부), 오프사이드/필드규격. → 현장 첫 30분 자료로 `state_from_obs()` 보정.

## 3. 우승 전략 — 3대 기둥

### 기둥 ① 역할 특화 (anti-swarm) ★최우선
```
GK   골문 앞 좁은 존, 공이 박스 안일 때만 출동
DEF×2 자기 존(좌/우 백) 고수, 상대 공격수 마크, 전진 추격 금지
MID  플레이메이커 — 공 소유 시 전진 패스 1순위, 공간 창출
FWD  최전방, 상대 골문 라인 유지, 슛 레인지 진입 시 즉시 슛
```
"공간 점유"가 "공 추격"을 이긴다. AI League "존만 통과, 나머지 회피"와 동형.

### 기둥 ② 결정 정책을 코드에 박기 (프롬프트 의존❌)
2초 안에 매번 LLM 추론 = 느리고 변동 큼. **결정론적 가드 우선, LLM은 회색지대만:**
```
공 소유:   슛레인지 → SHOOT | 전방 오픈 팀원 → PASS | 아니면 전진 DRIBBLE
공 미소유: 최근접 & 내 존 → PRESS | 아니면 포지션/마크 복귀
```
구현: `policy.py` 의 `decide_action()` (순수 함수, 테스트됨). LLM은 "동급 옵션 2개 택일"만.

### 기둥 ③ 레이턴시 = 실력 (500ms 예산)
- **기본 경로는 LLM 0회**: 런타임이 매 틱 `squad.act(role, obs)` 직접 호출 → 결정론 정책이 microsecond로 응답, 500ms 예산 압도적 여유 (베뉴 WiFi 나빠도 안전)
- LLM은 **gray-zone 틱에만** 호출 (`squad.act_or_escalate`, `Decision.gray_zone=True`일 때만 — 슛 vs 패스 경계 등). 95%+ 틱은 모델 안 탐
- 무거운 전략은 사전계산해 코드 상수로 (포메이션·존 좌표·임계거리 — `policy.py` 상단)
- 예외 시 fallback(`move` to 앵커) 보장 — AI League "empty path 절대 금지"와 동형

## 4. 기술 아키텍처 (Strands)
- **기본 = 역할 `Agent` 5개 독립** (`squad.build_role_agents`). 런타임이 각 선수 에이전트를 per-tick 호출한다는 **가정** `[ASSUMPTION — squad.py 헤더와 일치: 포털 연동 방식 미확인, 현장 첫 30분 확인]` 에 맞춘 형태. **Strands `Graph`는 옵션**(`build_squad_graph`) — 포털이 단일 Graph 아티팩트를 요구할 때만. Swarm의 auto-handoff는 ball-chasing 재현 위험 있어 회피.
- per-tick 진입점은 **`squad.act()` (결정론, LLM 0회)**; gray-zone만 `act_or_escalate`로 LLM 위임.
- 정책은 순수 함수(거리/오픈성/슛레인지/최근접 판정) — 외부 API 호출 없음(실격 룰 안전).
- **full-state 관측 → 각 에이전트가 "내가 최근접인가"를 독립 계산** → 통신 없이 정확히 1명만 압박(동거리 타이는 좌표 lexicographic으로 결정론적 분리). 이게 anti-swarm의 수학적 근거.

## 5. 토너먼트 운영 (시간배분)
1. **빌드 30분: deploy-first.** 5역할 baseline squad를 무조건 먼저 피치에 (HK 배포지연 반복 금지).
2. **1차 매치 = 관찰.** 뭉침/실점 패턴 기록.
3. **튜닝 라운드 = 승부처.** 존 좌표·패스 임계·압박 트리거 **숫자만** 한 번에 하나씩 조정 (회귀 방지).
4. **결승: 맵/상대 하드코딩 금지** — 일반화 정책 유지 `[전이]`.

## 6. 준비물 / 사전 확인 (6/24 전)
- [ ] Strands SDK + AgentCore quickstart 30분 예습 (`pip install strands-agents`, Graph 예제 1개)
- [ ] 노트북 + AWS 계정 (현장 임시계정 가능) `[VERIFIED: 需自带电脑]`
- [ ] 역할 프롬프트 4종 초안 → `prompts/` (현장은 숫자 튜닝만)
- [ ] 결정 가드 → `policy.py` (테스트 green 유지)
- [ ] 6/23 AI League에서 모델 dropdown / 동시성 hang 여부 확인 → 6/24 전이

## 7. 리스크 / 빈틈
1. **상태 dict 필드명·좌표계만 미확인** `[부분해소]` — 액션(11개)·관측 항목(공/선수/스태미나/스코어)·500ms는 VERIFIED. 남은 건 **정확한 key 이름과 x/y 방향**뿐. 현장 첫 30분에 `state_from_obs()` 한 곳만 고치면 됨. (AI League "playbook이 memory를 이긴다"와 동일.)
2. **500ms 데드라인** `[VERIFIED, 상향]` — 2초가 아니라 500ms. LLM 매틱 왕복은 위험 → 기둥②(결정론 정책) 우선이 정답. LLM은 회색지대 타이브레이크만, 그것도 500ms 클리어 확인 후.
3. **모델 자유선택 확정** `[해소]` — Nova/Claude/임의 Bedrock. 가벼운 모델 기본, 무거운 모델은 latency 통과 시만.
4. **Strands Graph vs Swarm** — Swarm 자율적이나 ball-chasing 재현 위험. **Graph 고정 역할 채택**(검증됨: `squad.py`). Swarm의 auto-handoff tool이 5명을 공으로 끌어모을 수 있음.
5. **스코어링 세부 미공개** — 골 차가 1차이나 가점(점유/패스성공 등) 존재 가능. 현장 리더보드로 즉시 확인 후 정책 가중치 조정.

**한 줄 결론:** 6/23에서 배운 3가지(deploy-first / 정책은 코드에 / terse·저지연)를 그대로, Football Cup 천장 돌파 열쇠는 **역할 특화로 ball-chasing을 죽이는 것.** 현장 스키마 받는 즉시 숫자만 보정.

---
**Sources:** agenticfootballcup.com · aws.amazon.com/startups/events/agentic-football-cup-singapore · github.com/strands-agents · arxiv 2305.09458 (GRF 표준)
