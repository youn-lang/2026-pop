from pathlib import Path
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------
st.set_page_config(
    page_title="지역별 인구 구조",
    page_icon="👥",
    layout="wide",
)

DATA_FILE = "202606_202606_연령별인구현황_월간.csv"
DATA_PATH = Path(__file__).parent / DATA_FILE


# --------------------------------------------------
# 데이터 로드 및 전처리
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data(path: Path) -> pd.DataFrame:
    """CSV를 읽고 인구 관련 열을 숫자형으로 변환한다."""
    encodings = ("cp949", "utf-8-sig", "utf-8")
    last_error = None

    for encoding in encodings:
        try:
            df = pd.read_csv(path, encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        raise RuntimeError(
            "CSV 인코딩을 확인할 수 없습니다. CP949 또는 UTF-8 형식인지 확인하세요."
        ) from last_error

    df.columns = df.columns.str.strip()

    if "행정구역" not in df.columns:
        raise ValueError("CSV에서 '행정구역' 열을 찾을 수 없습니다.")

    df["행정구역"] = df["행정구역"].astype(str).str.strip()
    df["지역명"] = (
        df["행정구역"]
        .str.replace(r"\s*\(\d+\)\s*$", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    df["행정구역코드"] = df["행정구역"].str.extract(r"\((\d+)\)\s*$", expand=False)

    population_columns = [
        col for col in df.columns
        if col not in {"행정구역", "지역명", "행정구역코드"}
    ]

    for col in population_columns:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False).str.strip(),
            errors="coerce",
        ).fillna(0)

    return df


@st.cache_data(show_spinner=False)
def build_age_column_map(columns: tuple[str, ...]) -> tuple[str, dict[str, dict[int, str]]]:
    """연월과 성별별 연령 열을 자동으로 탐색한다."""
    pattern = re.compile(
        r"^(?P<period>\d{4}년\d{2}월)_(?P<sex>계|남|여)_(?P<age>\d+세|100세 이상)$"
    )

    mapping: dict[str, dict[int, str]] = {"계": {}, "남": {}, "여": {}}
    periods: list[str] = []

    for col in columns:
        match = pattern.match(col)
        if not match:
            continue

        period = match.group("period")
        sex = match.group("sex")
        age_text = match.group("age")
        age = 100 if age_text == "100세 이상" else int(age_text.replace("세", ""))

        mapping[sex][age] = col
        periods.append(period)

    if not periods or not all(mapping[sex] for sex in ("계", "남", "여")):
        raise ValueError("연령별 인구 열을 자동으로 인식하지 못했습니다.")

    return periods[0], mapping


def make_age_dataframe(
    row: pd.Series,
    column_map: dict[str, dict[int, str]],
) -> pd.DataFrame:
    ages = sorted(set(column_map["계"]) | set(column_map["남"]) | set(column_map["여"]))

    records = []
    for age in ages:
        records.append(
            {
                "연령": age,
                "연령표시": "100세 이상" if age == 100 else f"{age}세",
                "전체": float(row.get(column_map["계"].get(age), 0)),
                "남성": float(row.get(column_map["남"].get(age), 0)),
                "여성": float(row.get(column_map["여"].get(age), 0)),
            }
        )

    return pd.DataFrame(records)


def find_total_column(columns: list[str], period: str, sex: str) -> str:
    candidate = f"{period}_{sex}_총인구수"
    if candidate not in columns:
        raise ValueError(f"'{candidate}' 열을 찾을 수 없습니다.")
    return candidate


# --------------------------------------------------
# 화면 구성
# --------------------------------------------------
st.title("지역별 인구 구조 대시보드")
st.caption("행정안전부 연령별 인구현황 CSV를 이용해 선택 지역의 연령별 인구 분포를 표시합니다.")

if not DATA_PATH.exists():
    st.error(
        f"데이터 파일을 찾을 수 없습니다: `{DATA_FILE}`\n\n"
        "`app.py`와 CSV 파일을 같은 폴더에 두고 다시 실행하세요."
    )
    st.stop()

try:
    df = load_data(DATA_PATH)
    period, age_column_map = build_age_column_map(tuple(df.columns))
except Exception as exc:
    st.exception(exc)
    st.stop()


# --------------------------------------------------
# 지역 검색 및 선택
# --------------------------------------------------
st.sidebar.header("지역 선택")

search_text = st.sidebar.text_input(
    "지역명 입력",
    placeholder="예: 종로구, 청운효자동, 서울특별시",
    help="입력한 글자가 포함된 지역만 아래 선택 목록에 표시됩니다.",
).strip()

if search_text:
    filtered_df = df[
        df["지역명"].str.contains(search_text, case=False, na=False, regex=False)
        | df["행정구역코드"].fillna("").str.contains(search_text, regex=False)
    ].copy()
else:
    filtered_df = df.copy()

if filtered_df.empty:
    st.sidebar.warning("검색어와 일치하는 지역이 없습니다.")
    st.info("다른 지역명이나 행정구역 코드를 입력하세요.")
    st.stop()

region_options = filtered_df.index.tolist()

selected_index = st.sidebar.selectbox(
    "검색 결과에서 선택",
    options=region_options,
    format_func=lambda idx: f"{df.at[idx, '지역명']} ({df.at[idx, '행정구역코드']})",
)

selected_row = df.loc[selected_index]
selected_region = selected_row["지역명"]
selected_code = selected_row["행정구역코드"]

value_mode = st.sidebar.radio(
    "그래프 표시 방식",
    options=("인구수", "지역 인구 대비 비율"),
    horizontal=False,
)

show_total = st.sidebar.checkbox("전체", value=True)
show_male = st.sidebar.checkbox("남성", value=True)
show_female = st.sidebar.checkbox("여성", value=True)

if not any((show_total, show_male, show_female)):
    st.sidebar.warning("전체, 남성, 여성 중 하나 이상을 선택하세요.")
    st.stop()


# --------------------------------------------------
# 지표 계산
# --------------------------------------------------
total_col = find_total_column(df.columns.tolist(), period, "계")
male_col = find_total_column(df.columns.tolist(), period, "남")
female_col = find_total_column(df.columns.tolist(), period, "여")

total_population = int(selected_row[total_col])
male_population = int(selected_row[male_col])
female_population = int(selected_row[female_col])

age_df = make_age_dataframe(selected_row, age_column_map)

working_age = int(age_df.loc[age_df["연령"].between(15, 64), "전체"].sum())
young_population = int(age_df.loc[age_df["연령"].between(0, 14), "전체"].sum())
old_population = int(age_df.loc[age_df["연령"] >= 65, "전체"].sum())

peak_row = age_df.loc[age_df["전체"].idxmax()]
peak_age = peak_row["연령표시"]
peak_population = int(peak_row["전체"])

st.subheader(f"{selected_region} 인구 구조")
st.caption(f"기준: {period} · 행정구역 코드: {selected_code}")

metric_cols = st.columns(5)
metric_cols[0].metric("총인구", f"{total_population:,}명")
metric_cols[1].metric("남성", f"{male_population:,}명")
metric_cols[2].metric("여성", f"{female_population:,}명")
metric_cols[3].metric("65세 이상", f"{old_population:,}명")
metric_cols[4].metric("최다 연령", peak_age, f"{peak_population:,}명")


# --------------------------------------------------
# Plotly 꺾은선 그래프
# --------------------------------------------------
fig = go.Figure()

series_settings = [
    ("전체", show_total),
    ("남성", show_male),
    ("여성", show_female),
]

for series_name, should_show in series_settings:
    if not should_show:
        continue

    if value_mode == "지역 인구 대비 비율":
        denominator = total_population if total_population else 1
        y_values = age_df[series_name] / denominator * 100
        hover_template = (
            "%{x}<br>"
            + series_name
            + ": %{customdata:,.0f}명<br>전체 인구 대비 %{y:.2f}%<extra></extra>"
        )
    else:
        y_values = age_df[series_name]
        hover_template = "%{x}<br>" + series_name + ": %{y:,.0f}명<extra></extra>"

    fig.add_trace(
        go.Scatter(
            x=age_df["연령표시"],
            y=y_values,
            customdata=age_df[series_name],
            mode="lines",
            name=series_name,
            line={"width": 2.5},
            hovertemplate=hover_template,
        )
    )

fig.update_layout(
    title={"text": f"{selected_region} 연령별 인구 분포", "x": 0.02},
    xaxis_title="연령",
    yaxis_title="비율(%)" if value_mode == "지역 인구 대비 비율" else "인구수(명)",
    hovermode="x unified",
    legend_title_text="구분",
    height=620,
    margin={"l": 20, "r": 20, "t": 70, "b": 30},
)

fig.update_xaxes(
    tickmode="array",
    tickvals=[f"{age}세" for age in range(0, 100, 5)] + ["100세 이상"],
    tickangle=-45,
    showgrid=False,
)
fig.update_yaxes(rangemode="tozero", gridcolor="rgba(128,128,128,0.18)")

st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})


# --------------------------------------------------
# 보조 정보
# --------------------------------------------------
summary_cols = st.columns(3)
summary_cols[0].metric(
    "0~14세",
    f"{young_population:,}명",
    f"{young_population / total_population * 100:.1f}%" if total_population else "0.0%",
)
summary_cols[1].metric(
    "15~64세",
    f"{working_age:,}명",
    f"{working_age / total_population * 100:.1f}%" if total_population else "0.0%",
)
summary_cols[2].metric(
    "65세 이상",
    f"{old_population:,}명",
    f"{old_population / total_population * 100:.1f}%" if total_population else "0.0%",
)

with st.expander("연령별 원자료 보기"):
    display_df = age_df[["연령표시", "전체", "남성", "여성"]].copy()
    for col in ("전체", "남성", "여성"):
        display_df[col] = display_df[col].astype(int)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "연령표시": "연령",
            "전체": st.column_config.NumberColumn("전체", format="%,d명"),
            "남성": st.column_config.NumberColumn("남성", format="%,d명"),
            "여성": st.column_config.NumberColumn("여성", format="%,d명"),
        },
    )

st.caption(f"사용 파일: {DATA_FILE}")
