# app.py (UTF-8)
import io
import os
import time
import base64
import random
import streamlit as st
from gtts import gTTS
from streamlit.components.v1 import html

st.set_page_config(page_title="カルタ読み上げ", page_icon="🗣️", layout="centered")

# ====== 設定（ここで2ファイルのパスを指定） ======
FILE_A = "karuta_A.txt"
FILE_B = "karuta_B.txt"

# rerun時に毎回 tmp.txt を空にするか（要件に合わせて True）
ALWAYS_CLEAR_TMP_ON_RERUN = True

TMP_FILE = "tmp.txt"

# ===== ボタン強調スタイル（任意） =====
st.markdown("""
<style>
div.stButton > button {
  font-size: 1.15rem; font-weight: 700;
  padding: 0.7rem 1rem; border-radius: 12px;
  border: 2px solid #16a34a; background: #bbf7d0;
}
div[data-testid="column"]:last-child div.stButton > button {
  border-color: #dc2626; background: #fecaca;
}
</style>
""", unsafe_allow_html=True)

# ===== ユーティリティ =====
def load_lines(path: str):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines()]
    return [ln for ln in lines if ln]

def load_tmp_set() -> set:
    if not os.path.exists(TMP_FILE):
        return set()
    with open(TMP_FILE, "r", encoding="utf-8") as f:
        return set([ln.strip() for ln in f if ln.strip()])

def append_tmp(text: str):
    if not text:
        return
    ex = load_tmp_set()
    if text in ex:
        return
    with open(TMP_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def clear_tmp():
    with open(TMP_FILE, "w", encoding="utf-8") as f:
        f.write("")

def ensure_state():
    ss = st.session_state
    ss.setdefault("source_choice", "A")     # A/B の選択
    ss.setdefault("file_name", FILE_A)      # 実際に読むファイルパス
    ss.setdefault("lines", [])
    ss.setdefault("order", [])              # シャッフル順（index）
    ss.setdefault("pos", 0)                 # 現在位置（index into order）
    ss.setdefault("started", False)         # 初回は押されるまで再生しない
    ss.setdefault("audio_bytes", None)
    ss.setdefault("audio_token", 0)
    ss.setdefault("last_play_ts", 0.0)
    ss.setdefault("await_next", False)
    ss.setdefault("lang", "ja")
    ss.setdefault("slow", False)
    ss.setdefault("repeat_sec", 1.0)        # 要件：1秒
    ss.setdefault("read_set", set())        # 既読 index
    ss.setdefault("read_history", [])       # 既読テキスト（順序）
    ss.setdefault("display_text", "")       # 画面表示用の現在の札（押下直後に更新）

def build_text_to_indices(lines):
    d = {}
    for i, t in enumerate(lines):
        d.setdefault(t, []).append(i)
    return d

def apply_tmp_to_readset():
    """tmp.txt にある既読テキストを read_set/read_history に反映"""
    tmp_seen = load_tmp_set()
    t2i = build_text_to_indices(st.session_state.lines)
    for txt in tmp_seen:
        for idx in t2i.get(txt, []):
            if idx not in st.session_state.read_set:
                st.session_state.read_set.add(idx)
                st.session_state.read_history.append(txt)

def shuffle_order():
    st.session_state.order = list(range(len(st.session_state.lines)))
    random.shuffle(st.session_state.order)
    st.session_state.pos = 0
    st.session_state.started = False
    st.session_state.audio_bytes = None
    st.session_state.await_next = False
    st.session_state.display_text = current_text()  # 表示も初期化
    # tmp.txt の内容を反映して既読はスキップ対象に
    st.session_state.read_set = set()
    st.session_state.read_history = []
    apply_tmp_to_readset()

def current_index() -> int:
    ss = st.session_state
    if not ss.lines:
        return -1
    n = len(ss.order)
    i = ss.pos
    # 未読になるまで pos を進める
    while i < n and ss.order[i] in ss.read_set:
        i += 1
    ss.pos = i
    return ss.order[i] if i < n else -1

def current_text() -> str:
    idx = current_index()
    if idx < 0:
        return ""
    return st.session_state.lines[idx]

def mark_read(idx: int, text: str):
    if idx >= 0 and idx not in st.session_state.read_set:
        st.session_state.read_set.add(idx)
        st.session_state.read_history.append(text)
        append_tmp(text)  # 永続化

def synth_say(text: str):
    """音声合成＋既読登録＋自動再生準備"""
    tts = gTTS(text=text, lang=st.session_state.lang, slow=st.session_state.slow)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    st.session_state.audio_bytes = buf.read()
    st.session_state.audio_token += 1
    st.session_state.last_play_ts = time.time()
    st.session_state.await_next = True
    # 既読登録
    idx = current_index()
    mark_read(idx, text)

def go_next() -> bool:
    """次の未読に進める。未読が無ければ False"""
    ss = st.session_state
    if not ss.lines:
        return False
    ss.pos += 1
    n = len(ss.order)
    while ss.pos < n and ss.order[ss.pos] in ss.read_set:
        ss.pos += 1
    return ss.pos < n

def js_autorefresh(ms: int = 1100):
    """一定時間後にリロード（リピート判定用）"""
    html(f"""
    <script>
      setTimeout(function(){{
        const u = new URL(window.location);
        u.searchParams.set('_t', Date.now().toString());
        window.location.href = u.toString();
      }}, {ms});
    </script>
    """, height=0)

def render_audio(mp3_bytes: bytes, token: int):
    """HTML5 audioで自動再生＆前の再生を停止"""
    b64 = base64.b64encode(mp3_bytes).decode("ascii")
    html(f"""
    <audio id="player-{token}" controls autoplay>
      <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
      Your browser does not support the audio element.
    </audio>
    <script>
      const others = document.querySelectorAll('audio[id^="player-"]');
      others.forEach(a => {{
        if (a.id !== "player-{token}") {{
          try {{ a.pause(); a.currentTime = 0; }} catch(e) {{}}
        }}
      }});
      const p = document.getElementById("player-{token}");
      if (p) {{
        const pr = p.play();
        if (pr !== undefined) pr.catch(_=>{{}});
      }}
    </script>
    """, height=80)

# ===== 初期化 & rerunごとの tmp 初期化 =====
ensure_state()
if ALWAYS_CLEAR_TMP_ON_RERUN:
    clear_tmp()  # ※要件：rerunで毎回クリア（必要に応じて False に）

# ===== サイドバー（読み上げファイルの選択：丸ボタン2つ） =====
st.sidebar.header("読み上げ対象")
choice = st.sidebar.radio(
    "テキストを選択", options=["A", "B"], index=0 if st.session_state.source_choice=="A" else 1,
    horizontal=False
)

# 選択変更時：ファイル切替え＋シャッフル、tmpもクリア
if choice != st.session_state.source_choice:
    st.session_state.source_choice = choice
    st.session_state.file_name = FILE_A if choice == "A" else FILE_B
    clear_tmp()
    try:
        st.session_state.lines = load_lines(st.session_state.file_name)
        shuffle_order()
        st.success(f"ファイルを切り替えました: {st.session_state.file_name}")
    except Exception as e:
        st.error(f"読込に失敗しました: {e}")

# その他設定
st.sidebar.header("設定")
st.session_state.slow = st.sidebar.checkbox("ゆっくり読み上げ（slow）", value=st.session_state.slow)

# ===== 起動時の自動読込（lines が空のとき） =====
if not st.session_state.lines:
    # ラジオ選択に応じて file_name を設定
    st.session_state.file_name = FILE_A if st.session_state.source_choice == "A" else FILE_B
    if os.path.exists(st.session_state.file_name):
        try:
            st.session_state.lines = load_lines(st.session_state.file_name)
            shuffle_order()
        except Exception as e:
            st.error(f"起動時の読み込みに失敗しました: {e}")

# ===== 本体UI =====
st.title("🗣️ カルタ読み上げアプリ")

if not st.session_state.lines:
    st.info("対象ファイルが見つかりません。FILE_A/FILE_B のパス設定を確認してください。")
    st.stop()

# 現在の札（表示は display_text を採用。ボタン押下で随時更新）
if not st.session_state.display_text:
    st.session_state.display_text = current_text()

st.subheader("現在の札")
st.write(f"**{st.session_state.display_text if st.session_state.display_text else '（未読の札はありません）'}**")

# 進捗
read_count = len(st.session_state.read_set)
total = len(st.session_state.lines)
st.caption(f"進捗: {read_count} / {total}")

# ===== ボタン行：左「次のカード」 右「最初から」 =====
col_next, col_reset = st.columns(2)
with col_next:
    next_clicked = st.button("⏭ 次のカード", use_container_width=True)
with col_reset:
    reset_clicked = st.button("🧹 最初から", use_container_width=True)

# 「最初から」：並び再シャッフル＋tmp.txtクリア
if reset_clicked:
    clear_tmp()
    shuffle_order()
    st.session_state.display_text = current_text()
    st.success("初期化しました。（並びをシャッフル & 既読をクリア）")

# 「次のカード」
if next_clicked:
    if not st.session_state.started:
        # 初回クリック：現在の未読を表示し直して→再生
        st.session_state.started = True
        st.session_state.display_text = current_text()
        synth_say(st.session_state.display_text)
    else:
        # 次の未読へ進め、表示し直して→再生
        has_next = go_next()
        st.session_state.display_text = current_text() if has_next else ""
        if has_next and st.session_state.display_text:
            synth_say(st.session_state.display_text)
        else:
            st.session_state.audio_bytes = None
            st.session_state.await_next = False
            st.info("未読の札がありません。「最初から」でリセットできます。")

# 自動リピート（次ボタン未クリックが1秒超なら同じ札を再読）
now = time.time()
if st.session_state.started and st.session_state.await_next and st.session_state.audio_bytes:
    elapsed = now - st.session_state.last_play_ts
    if elapsed >= st.session_state.repeat_sec:
        st.session_state.audio_token += 1
        st.session_state.last_play_ts = now
    else:
        ms = int((st.session_state.repeat_sec - elapsed) * 1000) + 100
        html(f"<script>setTimeout(()=>window.location.reload(), {max(ms,400)});</script>", height=0)

# 音声プレイヤー
if st.session_state.audio_bytes:
    render_audio(st.session_state.audio_bytes, st.session_state.audio_token)

# 既読の一覧（ボタンの下）
st.markdown("### すでに読んだ札")
if st.session_state.read_history:
    for t in reversed(st.session_state.read_history):
        st.markdown(f"- {t}")
else:
    st.write("（まだありません）")
