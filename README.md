# 공시 정정 영향 추적 에이전트

정정 전후 공시 원문을 비교하고, 변경 사실이 기업분석 메모의 어떤 주장에 영향을 주는지 근거와 함께 보여주는 실증 프로젝트다. 현재 구현은 **합성 fixture 기반 원문 검증 + LangGraph 오케스트레이션 + LangChain Chain·Retriever·Tool 기반 메모 영향 분석 + Gradio 시연 화면**까지 포함한다.

> 현재 기본 데모는 실제 DART 공시나 실제 LLM 결과가 아니라, 명시된 합성 공시와 결정적 fake 분석을 사용한다. 따라서 데모 성공을 실제 API·LLM 성능 검증으로 해석하면 안 된다.

## 핵심 흐름

```text
START
  → parse_filings       공시 원문 파싱 및 근거 위치 보존
  → compare_changes     정정 전후 구조화 필드 비교
  → analyze_claims      근거 검색·Tool 실행·메모 주장 추출·영향 분류·수정안 생성
  → conditional
      ├ complete        분석 완료
      └ needs_review    실패·미해결 항목 존재
  → END
```

LangGraph의 `StateGraph`에 명시적인 상태, 처리 노드, 일반 엣지와 조건부 엣지를 적용했다. `analyze_claims` 노드에서는 파싱된 `EvidenceBlock`을 LangChain `Document`로 변환해 Retriever로 검색하고, 증거 조회·비율 계산 Tool을 실행한다. LangChain Chain 모드에서는 `ChatPromptTemplate → ChatOpenAI → ClaimBatch 구조화 출력`으로 주장을 추출한다. 웹 검색, 다중 에이전트, 자동 승인 저장은 현재 범위에 포함하지 않았다.

## 빠른 실행

Python 3.11 이상이 필요하다.

```bash
cd disclosure-impact-agent
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent.demo
```

브라우저에서 `http://127.0.0.1:7860`으로 접속한다. 기본값은 `DATA_MODE=fixture`, `LLM_MODE=fake`이므로 API 키 없이 실행할 수 있다.

다른 포트를 사용하려면 다음과 같이 실행한다.

```bash
GRADIO_SERVER_PORT=7861 PYTHONPATH=src \
  .venv/bin/python -m disclosure_impact_agent.demo
```

데모에서는 합성 원문과 메모를 불러와 분석을 실행한 뒤 다음 내용을 확인할 수 있다.

- 공시의 금액·기간·상대방 등 구조화 값
- 정정 전후 변경과 원문 근거
- 메모의 주장별 영향 분류
- 근거에 연결된 제한적 수정 제안
- 실행된 LangGraph 노드와 `complete`/`needs_review` 상태

## 테스트

```bash
PYTHONPATH=src .venv/bin/pytest
```

현재 자동 테스트 45개가 통과했으며, 파싱·정규화·변경 계산·안전한 업로드·주장 분석·평가 데이터·OpenAI 어댑터 경계·LangGraph 분기와 LangChain Retriever/Tool을 검사한다.

LangChain 구성요소도 포함한다. `langchain` 모드는 `ChatPromptTemplate`과 구조화 출력 Chain으로 주장을 추출하고, 파싱된 `EvidenceBlock`을 오프라인 Retriever로 검색하며, 증거 조회·비율 계산 Tool을 실행한다. 숫자 계산과 증거 최종 검증은 계속 결정적 코드가 담당한다. 사용하려면 의존성을 설치한 뒤 `LLM_MODE=langchain`, `OPENAI_MODEL`을 설정한다.

## CLI 사용

합성 HTML 원문 쌍의 변경 결과를 JSON으로 확인한다.

```bash
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent \
  fixtures/synthetic/a_company_contract/original.html \
  fixtures/synthetic/a_company_contract/correction.html
```

합성 원문 쌍과 메모의 주장별 영향을 확인한다.

```bash
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent \
  fixtures/synthetic/a_company_contract/original.html \
  fixtures/synthetic/a_company_contract/correction.html \
  --memo fixtures/synthetic/a_company_contract/memo.md
```

## OpenAI 모드 설정

실제 OpenAI 호출은 기본 실행에 필요하지 않다. 사용하려면 새로 발급한 키와 구조화 출력을 지원하는 모델을 환경변수로 지정한다. 모델명은 코드에 하드코딩되어 있지 않다.

```bash
export OPENAI_API_KEY="새로_발급한_키"
export OPENAI_MODEL="사용할_구조화_출력_지원_모델"
export LLM_MODE="openai"
export OPENAI_REASONING_EFFORT="low"  # reasoning 모델을 사용할 때 선택
```

`.env.example`을 복사해 사용할 수 있다. 애플리케이션이 프로젝트 루트의 `.env`를 자동으로 읽으므로 매번 `source`할 필요가 없다.

```bash
cp .env.example .env
# .env를 열어 OPENAI_API_KEY를 입력하고 LLM_MODE=openai로 변경
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent.demo
```

`.env`는 Git에서 제외된다. API 키가 들어간 파일은 커밋하지 않는다. 셸 환경변수와 `.env` 값이 모두 있으면 셸 값이 우선한다. 예시 모델 `gpt-5-mini`는 Responses API와 Structured Outputs를 지원하는 비용 민감형 소형 모델이며, 계정에서 사용할 수 없다면 접근 가능한 호환 모델로 바꾼다.

OpenAI 어댑터는 Responses API의 Pydantic 구조화 출력을 사용하고 `store=False`로 요청하며, 스키마 오류·타임아웃·거절·재시도 한도 초과를 `NO_IMPACT`로 숨기지 않는다. 화면에는 API 키의 설정 여부만 표시하고 키 자체는 출력하지 않는다.

## LangChain 모드

LangChain 모드는 OpenAI SDK 직접 호출 모드와 같은 그래프와 결정적 검증기를 사용하면서, 주장 추출을 LangChain LCEL Chain으로 조립한다. 현재 OpenAI SDK 버전과의 의존성 충돌을 피하기 위해 Chain은 `langchain-core`의 `ChatPromptTemplate`·`RunnableLambda`로 기존 Responses API 구조화 출력 어댑터를 감싼다. Retriever는 관련 근거 후보를 찾고, Tool은 검증된 증거 조회와 정확한 `Decimal` 비율 계산을 제공한다. 검색 결과와 Tool 결과는 그래프 상태에 기록되며, 최종 근거 인정·영향 분류·수정 허용 여부는 결정적 코드가 판정한다.

```bash
export OPENAI_API_KEY="새로_발급한_키"
export OPENAI_MODEL="사용할_구조화_출력_지원_모델"
export LLM_MODE="langchain"
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent.demo
```

`langchain-core`가 설치되어 있어야 하며, API 키가 없으면 외부 호출 없이 설정 보류로 종료한다.

## 주요 코드 위치

- `src/disclosure_impact_agent/demo.py`: Gradio 시연 화면과 샘플 실행
- `src/disclosure_impact_agent/graph.py`: LangGraph 상태와 노드·분기 구성
- `src/disclosure_impact_agent/parser.py`: HTML/XML/TXT 원문 파싱과 근거 위치 생성
- `src/disclosure_impact_agent/analysis.py`: 정정 전후 필드 변경과 비율 계산
- `src/disclosure_impact_agent/service.py`: 원문 비교와 메모 분석 연결
- `src/disclosure_impact_agent/memo_analysis.py`: 주장·영향·수정안 인터페이스와 분석 로직
- `src/disclosure_impact_agent/fake_llm.py`: 선언된 fixture 전용 결정적 테스트 대역
- `src/disclosure_impact_agent/openai_llm.py`: 선택적 OpenAI 구조화 출력 어댑터
- `src/disclosure_impact_agent/langchain_components.py`: LangChain Chain·Retriever·Tool 구성요소
- `evaluation/`: 12개 합성 시나리오와 60개 이상 주장 평가 입력·임시 정답
- `tests/`: 단계별 단위·통합 테스트

## 지원 범위

`fixtures/synthetic/a_company_contract/`에는 가상 A사의 계약금액 120억원→90억원 및 종료일 변경 사례가 실제 공시와 유사한 HTML 원문 형태로 들어 있다.

현재 파서는 다음 입력을 제한적으로 지원한다.

- `id="contract"`인 2열 필드 표
- 선택적인 `id="correction-table"` 3열 정정표
- `.html`/`.htm`, 외부 엔티티를 차단한 `.xml`
- `레이블: 값` 형식의 `.txt`
- 경로 이탈과 압축 해제 크기를 제한한 ZIP

지원하지 않는 구조는 값을 추측하지 않고 추출 미완료 또는 보류로 반환한다. 금액 원문과 정규화 값, 날짜, 미공개·빈값·0·추출 실패를 구분하며 근거는 보존된 문서의 표/행/셀 또는 문단 위치에 연결한다.

영향 분류는 다음 다섯 가지다.

- `DIRECT_FACT_CHANGE`
- `DERIVED_VALUE_CHANGE`
- `INTERPRETATION_REVIEW`
- `NO_IMPACT`
- `UNRESOLVED`

## 검증 상태와 한계

- 자동 테스트: 합성 fixture와 mock 경계 기준으로 검증
- 실제 DART 공시 파싱: **0건, 미검증**
- 실제 OpenAI API 구조화 출력 호출: **1건 성공** (synthetic 메모리 입력)
- 실제 DART 공시 기반 의미 성능: **미검증**
- Gradio 서버 기동과 페이지 응답: 로컬 환경에서 확인
- 평가 데이터: 계약 단위 12개 시나리오, 60개 이상 주장으로 구성
- 평가 정답: 실제 정답이 아니라 사람 검토 전 임시 정답
- fake 분석: 지정된 가상 A사 fixture에서만 성공하며 일반 LLM을 모사하지 않음

## 의도적으로 미룬 기능

현재 데모의 중심 흐름을 작게 유지하기 위해 다음은 후속 단계로 남겨 두었다.

- OpenDART 수집 및 실제 양식별 파서 확장
- 웹 검색, Tavily/Exa, ReAct 도구 호출
- 다중 에이전트와 병렬 보고서 생성
- LangGraph 체크포인터, 실제 `interrupt`/재개 승인 흐름
- 메모 수정 승인·버전 저장 및 외부 문서 반영
- 실제 LLM 고정 평가와 사람 정답 검수
- 투자 추천, 주가·실적 예측, 자동매매

현재 `needs_review`는 미해결 상태를 명시하는 종료 분기다. 승인 UI와 중단 후 재개는 데이터 저장 단계에서 추가할 수 있다. 데이터 확보 가능성과 제약은 `docs/DATA_FEASIBILITY.md`, 단계별 현황은 `docs/PROGRESS.md`에서 확인한다.
