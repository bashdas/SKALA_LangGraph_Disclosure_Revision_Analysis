# 종합 실습 보고서: 공시 정정 영향 추적 에이전트

## 1. 요구사항 정의

### 무엇을 만들 것인가

정정 전후의 공시 원문을 비교하고, 변경된 금액·기간·비율이 기업분석 메모의 어떤 주장에 영향을 주는지 찾아주는 분석 도구를 구현했다. 결과에는 변경 사실, 메모 주장, 영향 분류, 원문 근거, 수정 가능 여부를 함께 표시한다.

### 해결하려는 문제

공시가 정정되면 분석 메모에 적힌 계약 금액이나 종료일이 최신 정보와 달라질 수 있다. 사람이 원문을 다시 읽고 모든 메모 문장을 확인하는 과정은 누락되기 쉽다. 이 프로젝트는 원문 근거를 보존하면서 정정 영향 후보를 빠르게 검토할 수 있도록 돕는다.

### 주요 기능

- HTML/XML/TXT 원문에서 지원된 표 구조와 각주를 보존하며 필드 추출
- 문서 해시, 접수번호, 출처, 수집 시각, 파서 버전 및 근거 위치 기록
- 정정 전후 금액·날짜·비율의 결정적 변경 계산
- 계약 관계 후보 생성 및 관계 미확정 문서의 병합 방지
- 메모를 주장 단위로 분리하고 변경과 연결
- `DIRECT_FACT_CHANGE`, `DERIVED_VALUE_CHANGE`, `INTERPRETATION_REVIEW`, `NO_IMPACT`, `UNRESOLVED` 분류
- 근거 없는 숫자를 제안하지 않는 제한적 수정안 생성
- Gradio 화면에서 전체 흐름 시연

기본 데모는 실제 공시가 아닌 synthetic fixture와 결정적 fake 분석을 사용한다. 동일한 그래프에서 OpenAI SDK 직접 호출 방식과 LangChain Chain 방식을 선택할 수 있으며, 두 모드 모두 결정적 검증 단계를 통과한다.

## 2. 구현 내용

### 사용한 LangChain/LangGraph 기능

LangGraph를 상위 오케스트레이터로 두고 LangChain의 Chain·Retriever·Tool을 분석 노드 안에 결합했다. LLM은 주장 추출을 담당하고 Retriever는 관련 근거 후보를 조회하며, 금액 계산·근거 무결성·영향 확정·수정 허용 여부는 결정적 코드가 담당한다.

- `StateGraph`: 원문·메모·분석 결과를 명시적 상태로 관리
- 일반 엣지: 파싱 → 변경 계산 → 주장 영향 분석 순서 보장
- 조건부 엣지: 실패·미해결 항목은 `needs_review`, 검증 완료는 `complete`로 분기
- `START`, `END`: 실행 시작과 종료를 명확히 표현
- LCEL Chain: `ChatPromptTemplate → RunnableLambda → OpenAI Responses API ClaimBatch 구조화 출력`
- Retriever: `EvidenceBlock`을 LangChain `Document`로 변환해 관련 근거 후보 검색
- Tool: 검증된 증거 조회와 `Decimal` 기반 계약금액/매출액 비율 계산
- 상태 기록: 검색된 evidence ID와 Tool 반환 결과를 그래프 상태에 보존

웹 검색, 다중 에이전트, 자동 승인 저장은 핵심 문제를 흐리지 않기 위해 이번 범위에서 제외했다.

### 메인 그래프

파일: `src/disclosure_impact_agent/graph.py`

```python
builder = StateGraph(ReviewGraphState)
builder.add_node("parse_filings", parse_filings)
builder.add_node("compare_changes", compare_changes)
builder.add_node("analyze_claims", analyze_claims)
builder.add_node("complete_review", complete_review)
builder.add_node("mark_needs_review", mark_needs_review)

builder.add_edge(START, "parse_filings")
builder.add_edge("parse_filings", "compare_changes")
builder.add_edge("compare_changes", "analyze_claims")
builder.add_conditional_edges(
    "analyze_claims", route_result,
    {"complete": "complete_review", "needs_review": "mark_needs_review"},
)
builder.add_edge("complete_review", END)
builder.add_edge("mark_needs_review", END)

review_graph = builder.compile()
```

### Chain·Retriever·Tool 설계

`langchain_components.py`에서 메모 주장 추출 Chain, 공시 근거 Retriever, 읽기 전용 Tool을 정의한다. OpenAI SDK 직접 호출 어댑터를 `langchain-core`의 `ChatPromptTemplate`과 `RunnableLambda`로 조립해, 현재 고정된 OpenAI SDK 버전과 별도 provider 패키지의 의존성 충돌을 피했다.

- `ClaimBatch`: Chain의 구조화 출력 스키마
- `EvidenceRetriever`: 파싱된 근거 블록의 오프라인 키워드 검색
- `lookup_evidence`: evidence ID, 문서 해시, 원문 위치 조회
- `calculate_verified_ratio`: 검증된 정수 금액을 `Decimal`로 계산하며 0 분모는 보류

Retriever는 관련 근거 후보를 찾는 역할만 수행한다. 반환된 evidence ID와 문서 해시는 기존 증거 무결성 검증을 통과해야 하며, Tool은 승인·저장·원문 변경을 수행하지 않는다.

### 원문 비교와 영향 분석

`parser.py`가 원문을 `FilingDocument`와 `EvidenceBlock`으로 변환하고 문서 해시와 표/셀 위치를 저장한다. `analysis.py`는 Decimal 기반 금액 정규화, 날짜 비교, 정정표와 본문 대조, 매출액 대비 비율 재계산을 담당한다.

`memo_analysis.py`에는 다음 교체 가능한 인터페이스가 있다.

- `ClaimExtractor`: 메모 문장과 주장 구조화
- `ImpactAnalyzer`: 주장과 필드 변경 연결 및 영향 분류
- `RevisionProposer`: 검증된 값에 연결된 제한적 수정안 작성

`fake` 모드는 지정된 synthetic fixture 시나리오에서만 동작한다. `openai` 모드는 OpenAI Responses API와 Pydantic 구조화 출력을 직접 사용하고, `langchain` 모드는 `langchain-core` LCEL Chain으로 같은 구조화 출력 어댑터를 조립한다. 두 모드의 분석 결과는 동일한 결정적 영향 분석기와 수정 제안기를 통과한다. API 오류·타임아웃·스키마 오류는 영향 없음으로 숨기지 않고 실패/보류로 반환한다.

### 실행 방법

```bash
cd disclosure-impact-agent
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent.demo
```

브라우저에서 `http://127.0.0.1:7860`에 접속한다. 기본 fake 모드는 API 키가 필요 없다.

OpenAI SDK 직접 호출 모드:

```env
LLM_MODE=openai
OPENAI_MODEL=gpt-5-mini
OPENAI_API_KEY=새로_발급한_키
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=1
```

LangChain Chain 모드:

```env
LLM_MODE=langchain
OPENAI_MODEL=gpt-5-mini
OPENAI_API_KEY=새로_발급한_키
```

키는 Git에 커밋하지 않는다.

## 3. 실행 결과 및 검증

### 합성 fixture 결과

가상 A사 계약 원문에서 다음 변경을 확인했다.

| 필드 | 정정 전 | 정정 후 | 상태 |
|---|---:|---:|---|
| 계약금액 | 120억원 | 90억원 | changed |
| 계약종료일 | 2026-12-31 | 2027-03-31 | changed |
| 매출액 대비 비율 | 15% | 11.25% | changed |

같은 분모 800억원을 사용하는 경우 120억원은 15%, 90억원은 11.25%로 계산된다. 분모·통화·부가세 기준이 확인되지 않으면 자동 증감으로 확정하지 않고 검토 대상으로 둔다.

### 테스트 결과

```text
45 passed
```

검증한 범위는 다음과 같다.

- HTML 원문 파싱과 근거 무결성
- `120억원`과 `12,000,000,000원`의 동일 금액 정규화
- 금액·날짜·비율 변경 계산
- 미공개 상대방과 빈값/0의 구분
- 정정표와 본문 충돌 시 보류
- ZIP 경로 이탈·압축 해제 크기·XML 외부 엔티티 차단
- 메모 주장별 영향 분류와 수정안
- LangChain Retriever의 evidence 후보 검색과 증거 조회 Tool
- 비율 계산 Tool의 정확한 `Decimal` 계산 및 0 분모 보류
- LangGraph 정상/보류 분기
- Gradio 구성 및 API 키 누락 처리

### 실제 API 검증 상태

2026-09-15에 synthetic 원문과 메모를 입력으로 실제 OpenAI Responses API 구조화 출력 요청을 1회 실행했다. 결과는 `분석 완료`, `LLM 모드: openai`, `검토 주장: 5`, `보류: 0`, 그래프 종료 `complete_review`였다. 모델이 반환한 한국어 오프셋은 서버에서 원문 문자열을 재검색해 Python 오프셋으로 검증한 뒤 사용했다.

이 실행은 실제 LLM 호출과 구조화 응답 파싱 성공을 확인한 것이지만, 입력 공시가 synthetic이므로 실제 DART 문서에 대한 의미 성능 검증은 아니다. LangChain 모드는 동일한 `ClaimBatch` 스키마를 사용하는 선택 경로이며 `langchain-core`와 API 키가 필요한 환경에서 실행한다. 실제 공시 파싱과 고정 평가 성능은 여전히 미검증이다.

## 4. 어려웠던 점과 배운 점

### 어려웠던 점

1. 원문 HTML의 표 구조를 보존하면서도 필드 값과 근거 위치를 함께 관리해야 했다.
2. 정정표의 값과 본문 값이 다를 때 임의로 하나를 선택하지 않고 보류 사유를 반환해야 했다.
3. LLM이 실패했을 때 이를 `NO_IMPACT`로 오인하지 않도록 오류 경계를 분리해야 했다.
4. 메모 문장 하나에 사실 주장과 계산 주장이 함께 있을 수 있어 주장 단위 분리가 필요했다.

### 배운 점

- 그래프 상태와 노드를 작게 설계하면 전체 데이터 흐름을 쉽게 추적할 수 있다.
- 숫자 계산과 근거 검증은 LLM이 아니라 결정적 코드에 두는 것이 안전하다.
- Chain·Retriever·Tool은 조합을 단순화하지만, 검색 결과를 사실로 확정하는 검증기를 대체하지 않는다.
- fake는 테스트 속도를 높이지만 실제 LLM 성능을 증명하지 않으므로 검증 상태를 별도로 기록해야 한다.
- 조건부 분기를 사용하면 실패/보류를 성공 결과와 분리할 수 있다.

## 5. 추가 개선 계획

- 실제 DART 공시 수집과 양식별 파서 확장
- 실제 공시의 접수번호·정정 관계 자동 확인
- OpenAI 실제 평가 데이터와 사람 검토 정답 구축
- LangGraph 체크포인터와 중단 후 재개 가능한 승인 흐름
- 메모 버전 저장 및 승인된 수정만 반영
- 다수 계약과 반복 정정 문서의 관계 그래프 시각화
- 실제 서비스 배포 시 인증, 관찰성, 요청별 비용·토큰 기록 추가

## 프로젝트 산출물 위치

- 데모: `src/disclosure_impact_agent/demo.py`
- LangGraph 및 실행 상태: `src/disclosure_impact_agent/graph.py`
- LangChain Chain·Retriever·Tool: `src/disclosure_impact_agent/langchain_components.py`
- 원문 파서: `src/disclosure_impact_agent/parser.py`
- 변경 계산: `src/disclosure_impact_agent/analysis.py`
- 메모 영향 분석: `src/disclosure_impact_agent/memo_analysis.py`
- 합성 원문: `fixtures/synthetic/a_company_contract/`
- 테스트: `tests/`
