# 공시 정정 영향 추적 에이전트

정정 전후 공시를 비교해 사용자의 기업분석 메모에서 수정 또는 재검토가 필요한 주장을 근거와 함께 찾는 프로젝트다. 현재는 **2단계 메모 영향 분석 실증**까지 구현되어 있다. LangGraph와 승인 저장은 아직 구현하지 않았다.

## 실행

Python 3.11 이상이 필요하다.

```bash
cd disclosure-impact-agent
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Gradio 데모 실행:

```bash
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent.demo
```

실행 후 브라우저에서 `http://127.0.0.1:7860`으로 접속한다. 기본 화면은 합성 공시와 fake 분석을 사용하므로 API 키 없이 시연할 수 있다.

테스트:

```bash
PYTHONPATH=src .venv/bin/pytest
```

합성 HTML 원문 쌍의 구조·변경 결과를 JSON으로 확인:

```bash
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent \
  fixtures/synthetic/a_company_contract/original.html \
  fixtures/synthetic/a_company_contract/correction.html
```

합성 원문 쌍과 메모의 주장별 영향을 확인:

```bash
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent \
  fixtures/synthetic/a_company_contract/original.html \
  fixtures/synthetic/a_company_contract/correction.html \
  --memo fixtures/synthetic/a_company_contract/memo.md
```

실제 OpenAI 모드는 안전한 새 키와 모델명을 셸 비밀 설정으로 제공한 경우에만 실행한다.

```bash
LLM_MODE=openai OPENAI_MODEL=<structured-output-compatible-model> \
PYTHONPATH=src .venv/bin/python -m disclosure_impact_agent \
  fixtures/synthetic/a_company_contract/original.html \
  fixtures/synthetic/a_company_contract/correction.html \
  --memo fixtures/synthetic/a_company_contract/memo.md
```

OpenAI 어댑터는 Responses API의 Pydantic 구조화 출력을 사용하고 `store=False`로 요청한다. 모델 출력의 문자 위치와 스키마는 서버에서 다시 검증한다.

기본값은 `DATA_MODE=fixture`, `LLM_MODE=fake`이며 API 키가 필요 없다. `.env.example`은 변수 목록일 뿐 자동 로딩되지 않으므로 셸 또는 실행 환경에서 변수를 설정한다. `fake` 성공은 실제 LLM 분석 성능이 아니다.

## 현재 데이터

`fixtures/synthetic/a_company_contract/`에는 가상 A사의 120억원→90억원 및 종료일 변경 사례가 HTML 원문 형태로 있다. 모든 파일은 synthetic으로 표시되어 있으며 실제 기업이나 DART 공시가 아니다. 실제 파일 업로드 후보 형식과 데이터 접근 한계는 `docs/DATA_FEASIBILITY.md`를 참고한다.

## 범위와 안전 경계

- 현재 파서가 지원하는 구조: `id="contract"`인 2열 필드 표와 선택적인 `id="correction-table"` 3열 정정표. `.html`/`.htm`, 안전한 `.xml`, `레이블: 값` 형식 `.txt`, 제한된 ZIP 컨테이너를 받는다. 이 구조는 synthetic fixture에서만 검증됐으며 실제 DART 양식 지원 확정 상태는 아니다.
- 메모는 한국어 일반 텍스트/Markdown, 기본 최대 5,000자다.
- 투자 추천, 실적·주가 예측, 자동매매, OCR, 상시 감시, 외부 문서 덮어쓰기는 제외한다.
- 실제 공시 확보 및 OpenDART API 호출은 DART 키 부재로 미실행이다.
- `OPENAI_API_KEY` 존재 여부와 무관하게 0단계에서는 LLM을 호출하지 않는다.
- `fake` 추출기는 선언된 가상 A사 fixture에서만 동작한다. 다른 입력을 성공으로 가장하지 않고 실패로 반환한다.
- 평가 입력은 `evaluation/inputs.json`, 임시 정답은 `evaluation/expected.json`에 분리되어 있다. 임시 정답은 사람 검토 전 확정 정답이 아니다.
