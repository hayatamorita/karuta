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

# ======== 読み上げ元テキスト（パスはここで指定）========
SOURCE_FILES = {
    "テキスト１": "karuta_v0.txt",
    "テキスト２": "karuta.txt",
}
TMP_FILE = "tmp.txt"

# =====（任意）ボタンスタイル =====
st.markdown("""
<style>
div.stButton > button {
  font-size: 1.10rem; font-weight: 700; padding: 0.6rem 1rem;
  border-radius: 12px; border: 2px solid #16a34a; background: #bbf7d0;
}
div[data-testid="column"]:last-child div.stButton > button {
  border-color: #dc2626; background: #fecaca;
}
</style>
""", unsafe_allow_html=True)

# ===== ユーティリティ =====
def load_lines(path: str):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    # 空行除去
    return [ln.strip() for ln in lines if ln.strip()]

def tmp_exists() -> bool:
    return os.path.exists(TMP_FILE)

def clear_tmp():
    with open(TMP_FILE, "w", encoding="utf-8") as f:
        f.write("")

def append_tmp(index: int, text: str):
    """tmp.txt に 'index<TAB>text' 形式で追記（重複防止）"""
    if index < 0 or not text:
        return
    seen = load_tmp_indices()
    if index in seen:
        return
    with open(TMP_FILE, "a", encoding="utf-8") as f:
        f.write(f"{index}\t{text}\n")

def load_tmp_indices() -> set:
    """tmp.txt から既読 index を読み出し（'idx\\ttext' 形式）"""
    if not tmp_exists():
        return set()
    s = set()
    with open(TMP_FILE, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            # フォーマット移行対策: 旧形式（textのみ）があれば無視
            parts = ln.split("\t", 1)
            try:
                idx = int(parts[0])
                s.add(idx)
            except Exception:
                # 旧形式は index 不明なので既読にしない（全札読了を優先）
                pass
    return s

def ensure_state():
    ss = st.session_state
    # --- セッション初回（ブラウザ再読込やRerunでリセットされる） ---
    if "initialized" not in ss:
        ss.initialized = True
        # ◆要件: rerun（初期化）時は tmp.txt を空に
        clear_tmp()

    ss.setdefault("source_label", list(SOURCE_FILES.keys())[0])
    ss.setdefault("source_path", SOURCE_FILES[ss["source_label"]])
    ss.setdefault("lines", [])
    ss.setdefault("order", [])            # シャッフル順（indexの列）
    ss.setdefault("pos", 0)               # 0-based
    ss.setdefault("started", False)       # 1枚目は押されるまで再生しない
    ss.setdefault("audio_bytes", None)
    ss.setdefault("audio_token", 0)
    ss.setdefault("last_play_ts", 0.0)
    ss.setdefault("await_next", False)
    ss.setdefault("lang", "ja")
    ss.setdefault("slow", False)
    ss.setdefault("repeat_sec", 1.0)      # 要件: 1秒
    ss.setdefault("read_set", set())      # 既読 index（tmp反映後）
    ss.setdefault("read_history", [])     # 表示用（text）

def shuffle_order():
    ss = st.session_state
    ss.order = list(range(len(ss.lines)))
    random.shuffle(ss.order)
    ss.pos = 0
    ss.started = False
    apply_tmp_as_read()  # tmp反映 → 未読先頭へ

def apply_tmp_as_read():
    """tmp の既読 index を反映し、pos を未読先頭に合わせる"""
    ss = st.session_state
    ss.read_set = load_tmp_indices()
    # 表示用履歴も更新（index順ではなく、追記順に近くならないので簡易再構築）
    ss.read_history = [ss.lines[i] for i in ss.read_set if 0 <= i < len(ss.lines)]
    # 未読先頭へ
    n = len(ss.order)
    i = ss.pos
    while i < n and ss.order[i] in ss.read_set:
        i += 1
    ss.pos = i

def current_index() -> int:
    ss = st.session_state
    if not ss.lines:
        return -1
    n = len(ss.order)
    i = ss.pos
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
    ss = st.session_state
    if idx >= 0 and idx not in ss.read_set:
        ss.read_set.add(idx)
        ss.read_history.append(text)
        append_tmp(idx, text)  # ◆indexで永続化（同文面でも別札扱い）

def synth_say(text: str):
    """合成→プレイヤー更新→既読登録"""
    tts = gTTS(text=text, lang=st.session_state.lang, slow=st.session_state.slow)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    st.session_state.audio_bytes = buf.read()
    st.session_state.audio_token += 1
    st.session_state.last_play_ts = time.time()
    st.session_state.await_next = True
    idx = current_index()
    mark_read(idx, text)

def go_next() -> bool:
    """次の未読へ。無ければ False"""
    ss = st.session_state
    if not ss.lines:
        return False
    ss.pos += 1
    n = len(ss.order)
    while ss.pos < n and ss.order[ss.pos] in ss.read_set:
        ss.pos += 1
    return ss.pos < n

def js_autorefresh(ms: int = 1050):
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

# ===== 初期化 =====
ensure_state()

# ===== サイドバー：読み上げセット選択（丸ボタン） =====
st.sidebar.header("読み上げセット")
labels = list(SOURCE_FILES.keys())
new_label = st.sidebar.radio("使用するテキストを選択", labels, index=labels.index(st.session_state.source_label))

# セット切替時：◆tmp をリセット → 読込 → シャッフル → tmp反映（空）
if new_label != st.session_state.source_label:
    st.session_state.source_label = new_label
    st.session_state.source_path = SOURCE_FILES[new_label]
    clear_tmp()  # ◆要件：切替時に tmp リセット
    try:
        st.session_state.lines = load_lines(st.session_state.source_path)
        shuffle_order()
        st.success(f"「{new_label}」を読み込みました（{len(st.session_state.lines)} 行）。")
    except Exception as e:
        st.error(f"読み込みに失敗しました: {e}")

# 起動時自動読み込み（未読み込み時）
if not st.session_state.lines:
    path = st.session_state.source_path
    if os.path.exists(path):
        try:
            st.session_state.lines = load_lines(path)
            shuffle_order()
        except Exception as e:
            st.error(f"起動時の読み込みに失敗しました: {e}")
    else:
        st.info(f"同じフォルダに `{path}`（UTF-8／1行=1札）を置いてください。")
        st.stop()

# ===== 画面ヘッダ =====
st.title("🗣️ カルタ読み上げアプリ")
st.caption(f"現在のセット：**{st.session_state.source_label}**（{st.session_state.source_path}）")

# ===== ボタン行 =====
col_next, col_reset = st.columns(2)
with col_next:
    next_clicked = st.button("⏭ 次のカード", use_container_width=True)
with col_reset:
    reset_clicked = st.button("🧹 最初から", use_container_width=True)

# ===== ボタン処理 =====
if reset_clicked:
    clear_tmp()     # ◆要件：手動リセットで tmp クリア
    shuffle_order() # 並び再シャッフル & tmp反映（空）
    st.success("初期化しました（並びシャッフル・既読クリア）。")

if next_clicked:
    if not st.session_state.started:
        st.session_state.started = True
        synth_say(current_text())              # 現在表示中の未読を読み上げ & 既読化
    else:
        has_next = go_next()
        if has_next:
            synth_say(current_text())          # 進めた未読を読み上げ
        else:
            # ここに来るのは「全札読了時」。案内だけ出して音声は止める。
            st.session_state.audio_bytes = None
            st.session_state.await_next = False
            st.info("すべて読み終えました。「最初から」でリセットしてください。")

# ===== 自動リピート（1秒） =====
now = time.time()
if st.session_state.started and st.session_state.await_next and st.session_state.audio_bytes:
    elapsed = now - st.session_state.last_play_ts
    if elapsed >= st.session_state.repeat_sec:
        st.session_state.audio_token += 1
        st.session_state.last_play_ts = now
    else:
        ms = int((st.session_state.repeat_sec - elapsed) * 1000) + 100
        js_autorefresh(max(ms, 350))

# ===== 表示（ボタン処理後に再取得して必ず更新） =====
cur_text = current_text()

# 進捗（既読枚数 / 合計）
read_count = len(st.session_state.read_set)
total = len(st.session_state.lines)
st.caption(f"進捗: {read_count} / {total}")

# 音声の描画
if st.session_state.audio_bytes:
    render_audio(st.session_state.audio_bytes, st.session_state.audio_token)

# 既読一覧
st.markdown("### すでに読んだ札")
if st.session_state.read_history:
    for t in reversed(st.session_state.read_history):
        st.markdown(f"- {t}")
else:
    st.write("（まだありません）")
