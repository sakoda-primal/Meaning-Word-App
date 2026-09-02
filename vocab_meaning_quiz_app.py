# ターミナルで実行
# cd study_app
# python -m streamlit run vocab_meaning_quiz_app.py

import html
import random
from datetime import date

import streamlit as st
from notion_client import Client

TOKEN = st.secrets["TOKEN"]
DATA_SOURCE_ID = st.secrets["DATA_SOURCE_ID"]
notion = Client(auth=TOKEN)

MASTERED_CORRECT_COUNT = 5
REVIEW_WRONG_COUNT = 3


def get_text_from_title(property_data):
    title_list = property_data.get("title", [])
    if not title_list:
        return ""
    return title_list[0].get("plain_text", "")


def get_text_from_rich_text(property_data):
    text_list = property_data.get("rich_text", [])
    if not text_list:
        return ""
    return "".join(item.get("plain_text", "") for item in text_list)


def get_multi_select_names(property_data):
    items = property_data.get("multi_select", [])
    return [item.get("name", "") for item in items] if items else []


def get_number(property_data):
    number = property_data.get("number")
    return 0 if number is None else int(number)


def get_date(property_data):
    date_data = property_data.get("date")
    return None if date_data is None else date_data.get("start")


@st.cache_data(show_spinner="Notionから単語帳を読み込んでいます...")
def load_words_from_notion():
    all_results = []
    response = notion.data_sources.query(data_source_id=DATA_SOURCE_ID)
    all_results.extend(response["results"])

    while response.get("has_more"):
        response = notion.data_sources.query(
            data_source_id=DATA_SOURCE_ID,
            start_cursor=response["next_cursor"],
        )
        all_results.extend(response["results"])

    words = []
    for row in all_results:
        properties = row["properties"]
        word = get_text_from_title(properties["用語"])
        description = get_text_from_rich_text(properties["説明"])
        categories = get_multi_select_names(properties["種別"])
        correct_count = get_number(properties["正解数"])
        wrong_count = get_number(properties["不正解数"])
        learning_date = get_date(properties["学習日"])

        if not word or not description:
            continue

        words.append(
            {
                "page_id": row["id"],
                "word": word,
                "description": description,
                "categories": categories,
                "correct_count": correct_count,
                "wrong_count": wrong_count,
                "learning_date": learning_date,
            }
        )
    return words


def increment_count(page_id, property_name, current_count):
    notion.pages.update(
        page_id=page_id,
        properties={property_name: {"number": current_count + 1}},
    )


def update_learning_date(page_id):
    notion.pages.update(
        page_id=page_id,
        properties={"学習日": {"date": {"start": date.today().isoformat()}}},
    )


def get_question_candidates(words):
    """正解数が5未満の用語だけを出題対象にする。"""
    return [
        item
        for item in words
        if item.get("correct_count", 0) < MASTERED_CORRECT_COUNT
    ]


def choose_question(words):
    candidates = get_question_candidates(words)
    if not candidates:
        return None

    # 1. 学習日が空欄の用語を最優先
    unlearned_words = [
        item for item in candidates if item.get("learning_date") is None
    ]
    if unlearned_words:
        return random.choice(unlearned_words)

    # 2. 不正解数が3以上なら優先復習
    review_words = [
        item
        for item in candidates
        if item.get("wrong_count", 0) >= REVIEW_WRONG_COUNT
    ]
    if review_words:
        highest_wrong_count = max(item["wrong_count"] for item in review_words)
        most_missed = [
            item
            for item in review_words
            if item["wrong_count"] == highest_wrong_count
        ]
        oldest_date = min(item["learning_date"] for item in most_missed)
        oldest_review_words = [
            item for item in most_missed if item["learning_date"] == oldest_date
        ]
        return random.choice(oldest_review_words)

    # 3. 学習済みは学習日が最も古いものを優先
    oldest_date = min(item["learning_date"] for item in candidates)
    oldest_words = [
        item for item in candidates if item["learning_date"] == oldest_date
    ]
    return random.choice(oldest_words)


def create_question(words):
    question = choose_question(words)
    if question is None:
        return None, []

    correct_description = question["description"]

    # 重複する説明を除き、別の意味を3件選ぶ。
    other_descriptions = list(
        dict.fromkeys(
            item["description"]
            for item in words
            if item["description"] != correct_description
        )
    )
    if len(other_descriptions) < 3:
        return question, []

    choices = random.sample(other_descriptions, 3)
    choices.append(correct_description)
    random.shuffle(choices)
    return question, choices


def initialize_session():
    defaults = {
        "session_correct_count": 0,
        "session_wrong_count": 0,
        "answered": False,
        "result": "",
        "selected_answer": None,
        "question": None,
        "choices": [],
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def set_new_question(words):
    question, choices = create_question(words)
    st.session_state.question = question
    st.session_state.choices = choices
    st.session_state.answered = False
    st.session_state.result = ""
    st.session_state.selected_answer = None


def metric_card(label, value, subtext="", accent="gold"):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    safe_subtext = html.escape(str(subtext))
    return f"""
    <div class="metric-card {accent}">
        <div class="metric-label">{safe_label}</div>
        <div class="metric-value">{safe_value}</div>
        <div class="metric-subtext">{safe_subtext}</div>
    </div>
    """


st.set_page_config(
    page_title="Vocabulary Mastery",
    page_icon="◆",
    layout="centered",
)

st.markdown(
    """
    <style>
    :root {
        --navy-950: #07111f;
        --navy-900: #0b1628;
        --navy-800: #111f35;
        --slate-700: #29364a;
        --slate-500: #64748b;
        --silver: #d7dde7;
        --ivory: #f5f3ed;
        --gold: #c7a45b;
        --gold-soft: #e2ca91;
        --success: #75a892;
        --danger: #c88181;
    }

    .stApp {
        background:
            radial-gradient(circle at 12% 0%, rgba(199,164,91,.10), transparent 26%),
            linear-gradient(145deg, var(--navy-950) 0%, var(--navy-900) 50%, #101827 100%);
        color: var(--silver);
    }

    [data-testid="stHeader"] {
        background: rgba(7, 17, 31, .72);
    }

    .block-container {
        max-width: 980px;
        padding-top: 2.2rem;
        padding-bottom: 4rem;
    }

    h1, h2, h3, p, label, [data-testid="stCaptionContainer"] {
        color: var(--silver) !important;
    }

    .brand-kicker {
        color: var(--gold-soft);
        font-size: .72rem;
        letter-spacing: .28em;
        text-transform: uppercase;
        margin-bottom: .35rem;
    }

    .brand-title {
        color: var(--ivory);
        font-size: clamp(2rem, 5vw, 3.35rem);
        font-weight: 650;
        line-height: 1.05;
        letter-spacing: .035em;
        margin: 0;
    }

    .brand-subtitle {
        color: #98a5b8;
        font-size: .92rem;
        letter-spacing: .08em;
        margin-top: .65rem;
        margin-bottom: 2rem;
    }

    .gold-line {
        width: 72px;
        height: 2px;
        background: linear-gradient(90deg, var(--gold), transparent);
        margin: 1rem 0 1.8rem;
    }

    .metric-card {
        min-height: 126px;
        padding: 1.15rem 1.1rem;
        background: linear-gradient(145deg, rgba(30,43,61,.94), rgba(15,26,43,.96));
        border: 1px solid #344158;
        border-top: 2px solid var(--gold);
        box-shadow: 0 16px 35px rgba(0,0,0,.22);
    }

    .metric-card.silver { border-top-color: #8996a8; }
    .metric-card.green { border-top-color: var(--success); }
    .metric-card.red { border-top-color: var(--danger); }

    .metric-label {
        color: #919db0;
        font-size: .73rem;
        letter-spacing: .13em;
    }

    .metric-value {
        color: var(--ivory);
        font-size: 2rem;
        font-weight: 650;
        margin: .35rem 0 .1rem;
    }

    .metric-subtext {
        color: #78869a;
        font-size: .74rem;
    }

    .section-label {
        color: var(--gold-soft);
        font-size: .7rem;
        letter-spacing: .24em;
        text-transform: uppercase;
        margin-top: 2.2rem;
        margin-bottom: .65rem;
    }

    .question-card {
        background: linear-gradient(135deg, #15243a 0%, #0b1628 100%);
        border: 1px solid #3a4659;
        border-left: 4px solid var(--gold);
        box-shadow: 0 22px 50px rgba(0,0,0,.28);
        padding: 2.4rem 1.5rem;
        margin-bottom: 1.35rem;
        text-align: center;
    }

    .question-hint {
        color: #8592a5;
        font-size: .72rem;
        letter-spacing: .2em;
        margin-bottom: .9rem;
    }

    .question-word {
        color: var(--ivory);
        font-size: clamp(1.65rem, 5vw, 2.8rem);
        font-weight: 650;
        letter-spacing: .025em;
        overflow-wrap: anywhere;
    }

    div[role="radiogroup"] {
        gap: .65rem;
    }

    div[role="radiogroup"] label {
        background: rgba(23, 35, 53, .9);
        border: 1px solid #354258;
        padding: .9rem 1rem;
        transition: border-color .15s ease, background .15s ease;
    }

    div[role="radiogroup"] label:hover {
        border-color: var(--gold);
        background: rgba(35, 48, 68, .95);
    }

    .stButton > button {
        min-height: 3.15rem;
        width: 100%;
        border-radius: 0;
        border: 1px solid #4c596d;
        background: #17253a;
        color: var(--ivory);
        font-weight: 650;
        letter-spacing: .06em;
    }

    .stButton > button:hover {
        border-color: var(--gold);
        color: var(--gold-soft);
        background: #1d2c43;
    }

    .stButton > button:disabled {
        background: #111b2a;
        color: #566276;
        border-color: #263247;
    }

    [data-testid="stProgressBar"] > div > div {
        background: linear-gradient(90deg, #8f733b, var(--gold-soft));
    }

    [data-testid="stAlert"] {
        border-radius: 0;
        background: rgba(22, 34, 51, .95);
        border: 1px solid #39465a;
    }

    hr {
        border-color: #29364a !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="brand-kicker">Notion Learning System</div>
    <div class="brand-title">Vocabulary Mastery</div>
    <div class="brand-subtitle">用語から正しい意味を選ぶ、4択単語クイズ</div>
    <div class="gold-line"></div>
    """,
    unsafe_allow_html=True,
)

initialize_session()
words = load_words_from_notion()

if len(words) < 4:
    st.error("4択クイズを作るには、用語と説明が入ったデータが4件以上必要です。")
    st.stop()

if st.session_state.question is None:
    set_new_question(words)

question_candidates = get_question_candidates(words)
today = date.today().isoformat()
mastered_count = len(words) - len(question_candidates)
unlearned_count = sum(
    1 for item in question_candidates if item.get("learning_date") is None
)
review_count = sum(
    1
    for item in question_candidates
    if item.get("learning_date") is not None
    and item.get("wrong_count", 0) >= REVIEW_WRONG_COUNT
)
today_studied_count = sum(
    1 for item in words if item.get("learning_date") == today
)
mastery_rate = mastered_count / len(words) if words else 0

st.markdown('<div class="section-label">Learning Overview</div>', unsafe_allow_html=True)
metric_columns = st.columns(4)
metric_values = [
    ("習得済み", f"{mastered_count}語", f"全{len(words)}語", "green"),
    ("今日の学習", f"{today_studied_count}語", "学習日が今日の用語", "gold"),
    ("優先復習", f"{review_count}語", "不正解数3回以上", "red"),
    ("習得率", f"{mastery_rate * 100:.1f}%", f"{mastered_count} / {len(words)}語", "silver"),
]
for column, values in zip(metric_columns, metric_values):
    with column:
        st.markdown(metric_card(*values), unsafe_allow_html=True)

st.progress(mastery_rate)
st.caption(
    f"未学習 {unlearned_count}語　｜　現在の出題対象 {len(question_candidates)}語"
)

session_total = (
    st.session_state.session_correct_count
    + st.session_state.session_wrong_count
)
session_accuracy = (
    st.session_state.session_correct_count / session_total * 100
    if session_total
    else 0
)

st.markdown('<div class="section-label">Current Session</div>', unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        metric_card("今回の正解", st.session_state.session_correct_count, "このセッション", "green"),
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        metric_card("今回の不正解", st.session_state.session_wrong_count, "このセッション", "red"),
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        metric_card("今回の正解率", f"{session_accuracy:.1f}%", f"回答数 {session_total}問", "silver"),
        unsafe_allow_html=True,
    )

if not question_candidates:
    st.balloons()
    st.success("すべての用語が正解数5回に到達しました。全問習得です！")
    st.stop()

question = st.session_state.question
choices = st.session_state.choices

if question is None:
    st.info("現在、出題対象の用語はありません。")
    st.stop()

if len(choices) < 4:
    st.error("4択を作るための重複しない説明が不足しています。")
    st.stop()

safe_word = html.escape(question["word"])
st.markdown('<div class="section-label">Question</div>', unsafe_allow_html=True)
st.markdown(
    f"""
    <div class="question-card">
        <div class="question-hint">SELECT THE CORRECT MEANING</div>
        <div class="question-word">{safe_word}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

answer = st.radio(
    "正しい意味を選んでください",
    choices,
    key="selected_answer",
    disabled=st.session_state.answered,
)

button_col1, button_col2 = st.columns(2)
with button_col1:
    if st.button(
        "回答する",
        key="answer_button",
        disabled=st.session_state.answered,
        use_container_width=True,
    ):
        st.session_state.answered = True
        if answer == question["description"]:
            st.session_state.result = "正解！"
            st.session_state.session_correct_count += 1
            increment_count(
                page_id=question["page_id"],
                property_name="正解数",
                current_count=question["correct_count"],
            )
            update_learning_date(question["page_id"])
        else:
            st.session_state.result = (
                f"不正解です。正しい意味は「{question['description']}」です。"
            )
            st.session_state.session_wrong_count += 1
            increment_count(
                page_id=question["page_id"],
                property_name="不正解数",
                current_count=question["wrong_count"],
            )
        st.rerun()

if st.session_state.answered:
    if st.session_state.result.startswith("正解"):
        st.success(st.session_state.result)
        if question["correct_count"] + 1 >= MASTERED_CORRECT_COUNT:
            st.info("この用語は正解数5回に到達したため、次回から出題対象外です。")
    else:
        st.error(st.session_state.result)
        if question["wrong_count"] + 1 >= REVIEW_WRONG_COUNT:
            st.warning("不正解数が3回以上になったため、優先復習の対象です。")

with button_col2:
    if st.button(
        "次の問題へ",
        key="next_button",
        disabled=not st.session_state.answered,
        use_container_width=True,
    ):
        st.cache_data.clear()
        refreshed_words = load_words_from_notion()
        set_new_question(refreshed_words)
        st.rerun()
