# Claude replies (newest at top)

## 11:00 re: q_test.txt

**문제 아님. 설계된 정상 출력이다.** `DIRECTION UNVERIFIED`는 에러가 아니라 "정적 obs 한 장만으로는 x축 방향(어느 쪽이 상대 골대인지)을 *원리상* 확인 불가"라는 정직한 표시야. reconcile.py가 일부러 거짓 GREEN을 안 띄우는 거지 (정적 샘플로 방향 자동판정 = 자기 컨벤션 되먹임 = 무의미, 그래서 안 함).

**진짜 봐야 할 건 윗줄이다:**
- `KEYS+CHAIN GREEN` 떴으면 → **배포해도 된다.** 키 매핑·5역할 전부 합법 액션 반환 = 정책 코어 정상. 방향만 미확인일 뿐.
- `FIXME ...` 떴으면 → 그건 진짜 문제. `state_from_obs()` 키부터 고쳐. (이게 안 떴으면 무시)

**UNVERIFIED 닫는 법 (2단계, 1분):**
1. **1차 매치 한 틱 눈으로 봐라** — 우리 FWD가 상대 골대 쪽(x 증가 방향)으로 가는지. 이게 진짜 게이트다.
2. 맞으면 → `FBALL_ATTACK=right python reconcile.py <obs>` 재실행 → `DIRECTION: OK` 뜸.
   거꾸로 뛰면 → `FBALL_ATTACK=left` → `FLIPPED` 뜸 → `state_from_obs()`에서 모든 엔티티 `x → 1.0 - x`, `vx → -vx` 한 곳만 고치고 재실행.

**한 줄:** UNVERIFIED는 "배포 막는 빨간불"이 아니라 "1번 매치 때 방향 한 번 확인하고 env 한 줄로 잠가라"는 안내. KEYS+CHAIN만 GREEN이면 지금 baseline 배포 진행해 — 배포지연이 6/23 패인이라 방향확인 기다리지 마.

_Channel live. Push a question with `push.bat`, then `pull.bat` to read answers here._
