import html
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="iSchedule Gantt",
    layout="wide"
)

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

HOUR_WIDTH = 180
PX_PER_MINUTE = HOUR_WIDTH / 60
LEFT_COL_WIDTH = 260
ROW_HEIGHT = 58

hours = list(range(3, 20))

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
    (df["עובד"] != "") &
    (df["עובד"] != "nan") &
    (df["טיסה"] != "") &
    (df["טיסה"] != "nan")
].copy()

# =========================
# התחלת ציר זמן דינמית
# =========================

earliest_minutes = df["התחלה"].apply(time_to_minutes).min()

timeline_start_minutes = max(
    0,
    earliest_minutes - 60
)

# =========================
# HOURS HEADER
# =========================

hours_html = ""

start_hour = timeline_start_minutes // 60

for hour in range(start_hour, start_hour + 24):

    left = (hour - start_hour) * HOUR_WIDTH

    label = f"{hour % 24:02d}:00"

    hours_html += f"""
    <div class="hour-line" style="left:{left}px;"></div>

    <div class="hour-label" style="
    left:{left + 34}px;
    transform:none;
">
    {label}
</div>
    """

rows_html = ""

df["_start_minutes"] = df["התחלה"].apply(time_to_minutes)

df = df[
    (df["עובד"].astype(str).str.strip() != "") &
    (df["טיסה"].astype(str).str.strip() != "") &
    (df["_start_minutes"] > 0)
].copy()

workers = (
    df.groupby("עובד")["_start_minutes"]
    .min()
    .sort_values()
    .index
    .tolist()
)

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

for worker in workers:

    worker_df = df[df["עובד"] == worker].copy()
    worker_df = worker_df.sort_values("_start_minutes").copy()
    worker_df["conflict"] = False

    prev_end = -1

    for idx, r in worker_df.iterrows():
        s = time_to_minutes(r["התחלה"])
        e = time_to_minutes(r["סיום"])

        if s < prev_end:
            worker_df.loc[idx, "conflict"] = True

        prev_end = max(prev_end, e)

    tasks_html = ""

    for _, row in worker_df.iterrows():

        flight = esc(row["טיסה"])

        start_minutes = time_to_minutes(row["התחלה"])
        end_minutes = time_to_minutes(row["סיום"])

        duration_hours = max((end_minutes - start_minutes) / 60, 1)
        task_width = max(duration_hours * HOUR_WIDTH, 90)

        start_x = max(
            0,
            ((start_minutes - timeline_start_minutes) / 60) * HOUR_WIDTH
        )

        role = str(row.get("תפקיד", "דייל")).strip()
        color = role_colors.get(role, "#facc15")

        if row.get("conflict", False):
            color = "#ef4444"
        conflict_class = "conflict" if row.get("conflict", False) else ""
       
        tasks_html += f"""
        <div class="task {conflict_class}"
            title="טיסה: {flight}&#10;עובד: {worker}&#10;תפקיד: {role}"
            style="
                left:{start_x}px;
                background:{color};
                width:{task_width}px;
            ">
            {flight}
        </div>
        """

    rows_html += f"""
    <div class="row">

        <div class="worker">
            {worker}
        </div>

        <div class="timeline">
            {tasks_html}
        </div>

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
}}

.gantt-shell {{
    width:100%;
    height:calc(100vh - 20px);

    direction: ltr;
    overflow:auto;

    border:1px solid #d7dce2;
    border-radius:14px;

    background:white;
}}

.gantt {{
    position: relative;
    width: max-content;
    min-width: {timeline_width + LEFT_COL_WIDTH}px;
}}

.topbar {{
    display: flex;
    flex-direction: row;
    direction: ltr;

    position: sticky;
    top: 0;
    z-index: 100;

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

    background: #ffffff;
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

    min-height: 64px;
    border-bottom: 1px solid #e5e7eb;
}}

.worker {{
    width: 260px;
    min-width: 260px;
    max-width: 260px;

    position: sticky;
    left: 0;
    z-index: 15;

    background: #eef2f7;
    color: #111827;

    border-left: 3px solid #94a3b8;
    border-bottom: 1px solid #d7dce2;

    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;

    padding: 0 12px;

    font-size: 16px;
    font-weight: 800;

    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    position: sticky;
    left: 0;
    z-index: 50;
}}

.timeline {{
    position: relative;
    width: {timeline_width}px;
    min-width: {timeline_width}px;
    flex-shrink: 0;

    background: #fafafa;

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

.task {{
    position: absolute;
    top: 16px;
    height: 34px;
    border-radius: 999px;

    transition: all 0.18s ease;
    cursor: pointer;

    display: flex;
    align-items: center;
    justify-content: center;

    padding: 0 14px;

    font-size: 13px;
    font-weight: 800;

    color: #111827;
    white-space: nowrap;

    box-shadow:
        inset 0 -1px 0 rgba(0,0,0,0.08),
        0 2px 4px rgba(0,0,0,0.10);

    z-index: 10;
}}

.task:hover {{
    transform: translateY(-2px) scale(1.03);
    box-shadow: 0 8px 18px rgba(0,0,0,0.22);
    z-index: 80;
}}

.task.conflict {{
    border: 2px solid #ef4444 !important;
    box-shadow: 0 0 14px rgba(239, 68, 68, 0.95) !important;
    animation: conflictPulse 1.4s infinite;
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