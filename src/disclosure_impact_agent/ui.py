import streamlit as st

from disclosure_impact_agent.config import get_settings

settings = get_settings()

st.set_page_config(page_title="공시체크", page_icon="📋", layout="wide")
st.title("공시체크")
st.caption("정정 공시를 기준으로 메모에서 다시 확인할 문장을 찾습니다.")

left, right = st.columns(2)
left.metric("데이터 모드", settings.data_mode)
right.metric("LLM 모드", settings.llm_mode)

if settings.data_mode == "fixture":
    st.info("현재 합성 fixture 모드입니다. 실제 공시 또는 최신 공시를 확인한 결과가 아닙니다.")
if settings.llm_mode == "fake":
    st.warning("현재 fake LLM 모드입니다. 의미 분석 성능은 검증되지 않았습니다.")

st.subheader("1단계 원문 구조·변경 검증 준비 완료")
st.write("합성 HTML/XML/TXT/ZIP 입력에서 근거 위치를 보존해 구조화 필드와 변경을 계산합니다. 메모 영향 분석은 다음 단계에서 구현합니다.")
st.code("curl http://127.0.0.1:8000/health", language="bash")
