# 2단계 작은 실증 결과

실행일: 2026-09-15

## 데이터와 실행 모드

- 실제 공시: 0건
- 실제 LLM 호출: 0회
- 통합 실행: 가상 A사 synthetic HTML 2개 + synthetic 메모, `LLM_MODE=fake`
- fake 추출기는 `synthetic-a-company-contract-v1` 하나에만 허용되며 다른 시나리오는 명시적 실패다.
- 12개 synthetic 평가 시나리오와 60개 주장 후보를 개발 8/고정 평가 4로 분리했다. 반복 정정 두 시나리오는 같은 개발 분할에 있다.
- 평가 정답은 런타임 입력과 다른 파일에 있고 `provisional_not_human_reviewed`다. 고정 평가 성능 점수는 아직 산출하지 않았다.

## 개발 fixture 실제 결과

| 주장 | 분류 | 자동 수정 |
| --- | --- | --- |
| 120억원 | DIRECT_FACT_CHANGE | 90억원 제안 |
| 15% | DERIVED_VALUE_CHANGE | 서버 계산 11.25% 제안 |
| 2026년 말 | DIRECT_FACT_CHANGE | 2027-03-31 제안 |
| 2026년 전액 매출 반영 전망 | INTERPRETATION_REVIEW | 제외 |
| 산업용 장비 제조업체 | NO_IMPACT | 변경 없음 |

검토 주장 5개, 판단 보류 0개, 제안 3개였다. 제안의 관련 없는 문장 부분은 보존됐고 증거 위치 존재/구조화 값 의미 연결 검사가 모두 통과했다. 이 결과는 고정된 fake fixture의 결정적 회귀 결과이지 의미 분석 성능 측정이 아니다.

## 검증한 실패 유형

- 선언되지 않은 fake fixture → `fixture_mismatch`, 영향 없음으로 대체하지 않음.
- 추출 시간초과 → `timeout`, retryable 실패와 판단 보류 수 기록.
- OpenAI 모델 미설정 → `missing_model`.
- 불완전/거절 또는 parsed output 없음 → 제공자 실패.
- 잘못된 문장·주장 문자 위치 → 서버 스키마/원문 대조 실패.
- 계산 분모 기준 누락 → `UNRESOLVED`, 수정 금지.
- 공시 추출 미완료 상태의 `NO_IMPACT` → `UNRESOLVED`로 승격.

## OpenAI 구현과 미실행 사유

[공식 OpenAI Responses API 문서](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)에 따라 `responses.parse`, Pydantic `text_format`, 환경변수 모델, `store=False`, 제한된 timeout/retry를 사용한다. 공식 문서는 Responses API가 JSON 구조화 출력을 지원하고 `failed`/`incomplete` 상태가 존재함을 명시한다.

환경에는 `OPENAI_API_KEY`가 있으나 `OPENAI_MODEL`은 없다. 또한 사용자가 채팅에 게시한 키는 노출된 자격 증명이므로 사용하지 않았다. 안전하게 재발급한 키와 명시적 모델을 비밀 설정으로 제공한 뒤 README 명령으로 별도 평가해야 한다.

## 아직 미검증

- 실제 한국어 메모의 OpenAI 주장 분리·시점·계약 식별 정확도.
- 12개 데이터셋의 사람 정답 검토와 실제 LLM precision/recall.
- 실제 공시 기반 근거 의미 적합성.
- 문장 경계가 복잡하거나 중첩 편집인 입력의 광범위한 성능.
