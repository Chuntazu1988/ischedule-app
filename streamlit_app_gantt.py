import html
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="iSchedule Gantt", layout="wide")

st.title("📊 iSchedule Gantt")

EXCEL_PATH = "gantt_data.xlsx"

# =========================
# LOAD DATA
# =========================

df = pd.read_excel(EXCEL_PATH)

# ניקוי שמות עמודות
df.columns = df.columns.astype(str).str.strip()

# אם אין סטטוס, ניצור עמודת סטטוס ריקה
if "סטטוס" not in df.columns:
    df["סטטוס"] = ""

df = df.copy()

# =========================
# SETTINGS
# =========================

HOUR_WIDTH = 110
PX_PER_MINUTE = HOUR_WIDTH / 60
LEFT_COL_WIDTH = 190
ROW_HEIGHT = 42

timeline_start_minutes = 0

hours = list(range(0, 24)) + list(range(0, 6))
timeline_width = len(hours) * HOUR_WIDTH

# =========================
# HELPERS
# =========================


def esc(v):
    return html.escape(str(v))


def time_to_minutes(t):
    try:
        # אם זה שעה של אקסל / פייתון
        if hasattr(t, "hour") and hasattr(t, "minute"):
            return int(t.hour) * 60 + int(t.minute)

        s = str(t).strip()

        if s == "" or s.lower() == "nan":
            return 0

        parts = s.split(":")

        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0

        return h * 60 + m

    except:
        return 0


# =========================
# BUILD ROWS
# =========================


def time_to_minutes(t):
    try:
        if pd.isna(t):
            return 0

        if hasattr(t, "hour") and hasattr(t, "minute"):
            return int(t.hour) * 60 + int(t.minute)

        s = str(t).strip()

        if " " in s:
            s = s.split(" ")[-1]

        if ":" in s:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])

        return 0

    except:
        return 0


rows_html = ""

df["עובד"] = df["עובד"].astype(str).str.strip()
df["טיסה"] = df["טיסה"].astype(str).str.strip()

df = df[
    (df["עובד"] != "")
    & (df["עובד"] != "nan")
    & (df["טיסה"] != "")
    & (df["טיסה"] != "nan")
].copy()

# =========================
# התחלת ציר זמן דינמית
# =========================

timeline_start_minutes = 0

hours = list(range(0, 24)) + list(range(0, 6))

timeline_width = len(hours) * HOUR_WIDTH
hours_html = ""

for i, hour in enumerate(hours):
    left = i * HOUR_WIDTH
    label = f"{hour:02d}:00"

    hours_html += f"""
    <div class="hour-line" style="left:{left}px;"></div>

    <div class="hour-label" style="
    left:{left + 34}px;
    transform:none;
">
    {label}
</div>
    """

df["_start_minutes"] = df["התחלה"].apply(time_to_minutes)

df = df[
    (df["עובד"].astype(str).str.strip() != "")
    & (df["טיסה"].astype(str).str.strip() != "")
    & (df["_start_minutes"] > 0)
].copy()

workers = df.groupby("עובד")["_start_minutes"].min().sort_values().index.tolist()

role_colors = {
    "ראש צוות": "#2563eb",
    'ר"צ': "#2563eb",
    'טרייני ר"צ': "#60a5fa",
    "מפקח TSA": "#a855f7",
    "שומר TSA": "#22c55e",
    "מתאם תורים": "#ec4899",
    "דייל": "#facc15",
    "דייל 1": "#facc15",
    "דייל 2": "#facc15",
    "דייל 3": "#facc15",
    "דייל 4": "#facc15",
}

df["start_minutes"] = df["התחלה"].apply(time_to_minutes)
df["flight_sort_minutes"] = df["טיסה"].map(
    df.groupby("טיסה")["start_minutes"].min()
)

min_minutes = df["start_minutes"].min()
max_minutes = df["start_minutes"].max()

PX_PER_MINUTE = 2.2
LEFT_COL_WIDTH = 160

ROLE_COLORS = {
    "ראש צוות": "#8e24aa",
    "דיילת": "#5b9bd5",
    "דייל": "#5b9bd5",
    "מתאם תורים": "#ec4899",
    "אחמ״ש": "#facc15",
    "טריינר": "#22c55e",
    "TSA": "#ef4444",
}

flights = (
        df.groupby("טיסה")["start_minutes"]
        .min()
        .sort_values()
        .index
        .tolist()
    )

for flight in flights:
    flight_df = df[df["טיסה"] == flight].copy()
    flight_df = flight_df.sort_values("start_minutes").copy()

    flight_df["conflict"] = False

    for worker_name in flight_df["עובד"].dropna().unique():
        worker_tasks = df[df["עובד"] == worker_name].sort_values("start_minutes").copy()

        prev_end = -1

        for idx, r in worker_tasks.iterrows():
            s = time_to_minutes(r["התחלה"])
            e = time_to_minutes(r["סיום"])

            if e < s:
                e += 24 * 60

            if s < prev_end:
                if idx in flight_df.index:
                    flight_df.loc[idx, "conflict"] = True

            prev_end = max(prev_end, e)

    worker_rows_html = ""

    for _, row in flight_df.iterrows():
        worker = str(row["עובד"])
        role = str(row.get("תפקיד בסיס", ""))

        start_minutes = time_to_minutes(row["התחלה"])
        end_minutes = time_to_minutes(row["סיום"])

        if end_minutes < start_minutes:
            end_minutes += 24 * 60

        left = LEFT_COL_WIDTH + ((start_minutes - min_minutes) * PX_PER_MINUTE)
        width = max(60, (end_minutes - start_minutes) * PX_PER_MINUTE)

        worker_conflict = bool(row.get("conflict", False))
        block_class = "task-conflict" if worker_conflict else "task-ok"

        worker_rows_html += f"""
        <div class="worker-task-row">
            <div class="worker-name">
                {'⚠️ ' if worker_conflict else ''}
                {esc(worker)}
            </div>

            <div class="worker-task-area"
                data-worker="{esc(worker)}"
                ondragover="allowDrop(event)"
                ondrop="dropTask(event)">
                <div class="task-block {block_class}"
                    draggable="true"
                    data-worker="{esc(worker)}"
                    data-flight="{esc(flight)}"
                     style="
                        left:{left}px;
                        width:{width}px;
                     ">
                    <div class="task-role">
                        {esc(role)}
                    </div>

<div class="task-time">
    {esc(row["התחלה"])}-{esc(row["סיום"])}
</div>
                </div>
            </div>
        </div>
        """

    rows_html += f"""
    <div class="flight-group">
        <div class="flight-header">
            <div class="flight-title">
                {esc(flight)}
            </div>

            <div class="flight-meta">
                ✈️ 787 • {len(flight_df)} עובדים
            </div>
        </div>

        {worker_rows_html}
    </div>
    """
    

# =========================
# PAGE
# =========================

from datetime import datetime

now = datetime.now()
now_minutes = now.hour * 60 + now.minute
now_left = LEFT_COL_WIDTH + (now_minutes * PX_PER_MINUTE)
now_label = now.strftime("%H:%M")

page = f"""
<!DOCTYPE html>
<html dir="rtl">

<head>

<style>

.role-header {{
    background:#111827;
    color:white;

    font-size:18px;
    font-weight:900;

    padding:12px 18px;

    border-bottom:2px solid #374151;

    position:sticky;
    left:0;
    z-index:120;
}}

* {{
    box-sizing: border-box;
}}

body {{
    margin:0;
    background:#f4f5f7;
    font-family:Arial,sans-serif;

    overflow:hidden;
}}

.gantt-shell {{
    width:100%;

    height: fit-content;
    max-height: calc(100vh - 20px);

    direction:ltr;
    overflow:auto;

    border:1px solid #d7dce2;
    border-radius:14px;
    background:white;
}}

.gantt {{
    position: relative;
    width: {timeline_width + LEFT_COL_WIDTH}px;
    min-width: {timeline_width + LEFT_COL_WIDTH}px;

    background:
        repeating-linear-gradient(
            to right,
            #fafafa 0,
            #fafafa {LEFT_COL_WIDTH}px,
            #eef2f7 {LEFT_COL_WIDTH}px,
            #eef2f7 calc({LEFT_COL_WIDTH}px + 1px),
            transparent calc({LEFT_COL_WIDTH}px + 1px),
            transparent calc({LEFT_COL_WIDTH}px + {HOUR_WIDTH}px)
    ),
    #fafafa;

  }}

.topbar {{
    display: flex;
    flex-direction: row;
    direction: ltr;

    position: sticky;
    top: 0;
    z-index: 500;
    background: #ffffff;
    border-bottom: 1px solid #d7dce2;
}}

.worker-title {{
    width: {LEFT_COL_WIDTH}px;
    min-width: {LEFT_COL_WIDTH}px;
    max-width: {LEFT_COL_WIDTH}px;

    background: #eef2f7;
    color: #111827;

    border-left: 3px solid #94a3b8;
    border-bottom: 1px solid #d7dce2;

    display: flex;
    align-items: center;
    justify-content: center;

    font-size: 16px;
    font-weight: 900;

    position: sticky;
    left: 0;
    z-index: 150;

    direction: rtl;
}}

.time-title {{
    position: sticky;
    top: 0;
    z-index: 20;

    width: {timeline_width}px;
    min-width: {timeline_width}px;
    height: 60px;

    background:
        repeating-linear-gradient(
            to right,
            #eef2f7 0,
            #eef2f7 1px,
            transparent 1px,
            transparent {HOUR_WIDTH}px
        ),
        #ffffff;

    flex-shrink: 0;
}}

.hour-label {{
    position:absolute;

    top:18px;

    transform:translateX(-50%);

    color:#64748b;
    font-size:14px;
}}

.row {{
    display: flex;
    flex-direction: row;
    direction: ltr;
    height:74px;
    width: {timeline_width + LEFT_COL_WIDTH}px;
    min-width: {timeline_width + LEFT_COL_WIDTH}px;
    min-height: {ROW_HEIGHT}px;
    border-bottom: 1px solid #e5e7eb;
}}

.worker {{
    width: 260px;
    min-width: 260px;
    max-width: 260px;

    background: #eef2f7;
    color: #111827;

    border-left: 3px solid #94a3b8;
    border-bottom: 1px solid #d7dce2;

    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;

    padding: 0 08px;

    font-size: 14px;
    font-weight: 800;

    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    position: sticky;
    left: 0;
    z-index: 50;
    box-shadow: 4px 0 12px rgba(0,0,0,0.08);
}}
.timeline {{
    position: relative;
    width: {timeline_width}px;
    min-width: {timeline_width}px;
    flex-shrink: 0;

    height: 100%;
    min-height: 64px;

    background:
        repeating-linear-gradient(
            to right,
            #eef2f7 0,
            #eef2f7 1px,
            transparent 1px,
            transparent {HOUR_WIDTH}px
        ),
        #fafafa;

    overflow: visible;
}}

.now-line {{
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: #ef4444;
    z-index: 40;
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.6);
}}

.now-label {{
    position: absolute;
    top: 4px;
    transform: translateX(-50%);
    background: #ef4444;
    color: white;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 7px;
    border-radius: 999px;
    z-index: 41;
}}

.flight-block{{
    position:absolute;
    top:8px;

    height:58px;

    border-radius:14px;

    color:white;
    font-weight:900;

    padding:8px 12px;

    cursor:pointer;

    box-shadow:0 4px 10px rgba(0,0,0,0.22);

    overflow:hidden;

    display:flex;
    flex-direction:column;
    justify-content:center;

    transition:0.18s;
}}

.flight-block:hover{{
    transform:translateY(-2px);
    box-shadow:0 10px 20px rgba(0,0,0,0.26);
}}

.flight-block-title{{
    font-size:15px;
    line-height:15px;
}}

.flight-block-status{{
    font-size:11px;
    margin-top:5px;
}}

.flight-block-count{{
    font-size:10px;
    opacity:0.9;
    margin-top:3px;
}}

.status-ok{{
    background:#2563eb;
}}

.status-missing{{
    background:#f59e0b;
}}

.status-conflict{{
    background:#dc2626;
}}

.status-danger{{
    background:#7f1d1d;
}}

    @keyframes conflictPulse {{
        0% {{
            filter: brightness(1);
        }}

        50% {{
            filter: brightness(1.18);
        }}

        100% {{
            filter: brightness(1);
        }}
    }}

.flight-group{{
    margin-bottom:14px;
    border-bottom:1px solid #d8dee8;
    background:white;
}}

.flight-header{{
    height:46px;
    display:flex;
    align-items:center;
    gap:14px;
    padding:0 14px;
    background:#eaf0f7;
    font-weight:900;
    color:#111827;
}}

.flight-title{{
    font-size:16px;
}}

.flight-meta{{
    font-size:13px;
    color:#475569;
}}

.worker-task-row{{
    display:flex;
    min-height:42px;
    border-bottom:1px solid #edf1f7;
}}

.worker-name{{
    width:180px;
    min-width:180px;
    padding:10px;
    background:#f1f5f9;
    font-size:13px;
    font-weight:800;
    color:#111827;
    direction:rtl;
}}

.worker-task-area{{
    position:relative;
    flex:1;
    min-height:42px;
    background:#ffffff;
}}

.task-block{{
    position:absolute;
    top:6px;
    height:30px;
    border-radius:10px;
    display:flex;
    align-items:center;
    justify-content:center;
    color:white;
    font-size:12px;
    font-weight:900;
    box-shadow:0 3px 8px rgba(0,0,0,0.2);
}}
.task-ok{{
    background:#2563eb;
}}
.task-conflict{{
    background:#dc2626;
}}
.task-role{{
    padding:0 10px;
    white-space:nowrap;
}}

.task-time{{
    font-size:10px;
    opacity:0.9;
    margin-top:2px;
}}
</style>

</head>

<body>

<div class="gantt-shell">

    <div class="gantt">

        <div class="now-line" style="left:{now_left}px;"></div>
        <div class="now-label" style="left:{now_left}px;">{now_label}</div>

        <div class="topbar">

        <div class="worker-title">
            עובדים
        </div>

        <div class="time-title">
            {hours_html}
        </div>

    </div>
        <div class="now-line" style="left:{now_left}px;"></div>
        <div class="now-label" style="left:{now_left}px;">{now_label}</div>
        
        {rows_html}

    </div>

</div>

<script>
function resetGanttScroll() {{
    const shell = document.querySelector('.gantt-shell');
    if (shell) {{
        shell.scrollLeft = 0;
        shell.scrollTop = 0;
    }}
    window.scrollTo(0, 0);
    document.documentElement.scrollLeft = 0;
    document.body.scrollLeft = 0;
}}

resetGanttScroll();

window.addEventListener('load', function() {{
    resetGanttScroll();

    let counter = 0;
    const timer = setInterval(function() {{
        resetGanttScroll();
        counter++;

        if (counter > 20) {{
            clearInterval(timer);
        }}
    }}, 200);
}});
</script>

</body>
</html>
"""
components.html(page, height=900, scrolling=True)