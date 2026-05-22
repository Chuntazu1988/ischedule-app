from datetime import timedelta

import pandas as pd

from utils.constants import (
    NARROW_REG_PREFIXES, WIDE_REG_PREFIXES, REMOTE_GATES,
    USA_TSA_DESTS, QUEUE_DESTS, TWO_TEAM_LEADS_DESTS,
    ROLE_ORDER, LATE_SHIFT_END_MAX,
    MAX_CONTINUOUS_WORK_MINUTES, NIGHT_BREAK_WINDOW_START, NIGHT_BREAK_WINDOW_END,
)
from utils.helpers import (
    clean_text, is_time_text, to_datetime_time, time_to_minutes, minutes_between,
    name_key, normalize_role_label,
    area_switch_penalty, classify_shift, shift_length, required_break,
)


# =========================
# FLIGHT RULES
# =========================

def get_body_type(flight):
    reg = clean_text(flight.get("רישוי", "")).upper()
    aircraft = clean_text(flight.get("סוג מטוס", "")).upper()

    if reg.startswith(NARROW_REG_PREFIXES):
        return "צר גוף"
    if reg.startswith(WIDE_REG_PREFIXES):
        return "רחב גוף"
    if aircraft.startswith(("737", "738", "739", "E")):
        return "צר גוף"

    return "רחב גוף"


def is_remote_gate(gate):
    return clean_text(gate).upper() in REMOTE_GATES


def get_pax(flight):
    value = flight.get("נוסעים", 0)
    if pd.isna(value) or clean_text(value) == "":
        return 0
    try:
        return int(float(value))
    except Exception:
        return 0


def get_requirements(flight):
    dest = clean_text(flight["יעד"]).upper()
    body = get_body_type(flight)
    pax  = get_pax(flight)

    req = {
        "ראש צוות":   1,
        "דייל":       1,
        "מתאם תורים": 0,
        "מפקח TSA":   0,
        "שומר TSA":   0,
        "טרייני רצ":  0,
    }

    if body == "צר גוף":
        req["דייל"] = 1 if pax <= 150 else 2
    else:
        if dest in USA_TSA_DESTS:
            req["דייל"]     = 4
            req["שומר TSA"] = 1
        else:
            req["דייל"] = 3

    if dest in TWO_TEAM_LEADS_DESTS:
        req["ראש צוות"] = 2

    if dest in QUEUE_DESTS:
        req["מתאם תורים"] = 1

    if dest in USA_TSA_DESTS:
        req["מפקח TSA"] = 1

    return req


def requirements_text(flight):
    req = get_requirements(flight)
    parts = []
    for role in ROLE_ORDER:
        amount = req.get(role, 0)
        if amount > 0:
            parts.append(role if amount == 1 else f"{role} × {amount}")
    return parts


def role_start_time(flight, role):
    departure    = to_datetime_time(flight["המראה"])
    body         = get_body_type(flight)
    remote_narrow = body == "צר גוף" and is_remote_gate(flight.get("גייט", ""))

    if role in {"ראש צוות", "מתאם תורים", "טרייני רצ"}:
        minutes_before = 60 if body == "צר גוף" else 75
    elif role == "דייל":
        minutes_before = 50 if body == "צר גוף" else 65
    elif role in {"מפקח TSA", "שומר TSA"}:
        minutes_before = 120
    else:
        minutes_before = 60

    if remote_narrow:
        minutes_before += 10

    return departure - timedelta(minutes=minutes_before)


def role_end_time(flight):
    return to_datetime_time(flight["המראה"])


# =========================
# SHIFT / AVAILABILITY
# =========================


def is_within_shift(emp, task_start, task_end):
    shift_start = clean_text(emp.get("תחילת משמרת", ""))
    shift_end   = clean_text(emp.get("סוף משמרת", ""))

    if not is_time_text(shift_start) or not is_time_text(shift_end):
        return False

    ts = task_start.hour * 60 + task_start.minute
    te = task_end.hour   * 60 + task_end.minute

    avail_str = clean_text(emp.get("זמינות", ""))
    if avail_str:
        for window in avail_str.split(","):
            if "-" not in window:
                continue
            try:
                ws, we = window.strip().split("-", 1)
                ws_m = time_to_minutes(ws.strip())
                we_m = time_to_minutes(we.strip())
                if we_m < ws_m: we_m += 1440
                ts_n = ts if ts >= ws_m else ts + 1440
                te_n = te if te >= ts_n % 1440 else te + 1440
                if te_n <= ts_n: te_n += 1440
                if ts_n >= ws_m and te_n <= we_m:
                    return True
            except Exception:
                pass
        return False

    s = time_to_minutes(shift_start)
    e = time_to_minutes(shift_end)

    if e <= s:
        e += 1440

    for ts_norm in [ts, ts + 1440]:
        te_norm = te if te > ts_norm % 1440 else te + 1440
        if te_norm <= ts_norm:
            te_norm += 1440
        if ts_norm >= s and te_norm <= e:
            return True

    return False


def assigned_minutes(assignments, emp_name):
    total = 0
    for task in assignments:
        if task["עובד"] != emp_name:
            continue
        if clean_text(task.get("התחלה", "")) == "" or clean_text(task.get("סיום", "")) == "":
            continue
        total += minutes_between(to_datetime_time(task["התחלה"]), to_datetime_time(task["סיום"]))
    return total


def has_room_for_break(assignments, emp, emp_name, start, end):
    length = shift_length(emp)
    if length == 0:
        return False
    current = assigned_minutes(assignments, emp_name)
    new = minutes_between(start, end)
    return current + new + required_break(emp) <= length


def get_terminal(gate):
    g = clean_text(gate).upper().strip()
    if g and g[0].isalpha():
        return g[0]
    return ""


def is_available(assignments, emp_name, start, end, emp_row=None, role=None, flight_gate=None):
    if emp_row is not None and emp_row.get("חולה", False):
        return False

    if emp_row is not None:
        blocked_str = clean_text(emp_row.get("חסימות", ""))
        if blocked_str:
            ts = start.hour * 60 + start.minute
            te = end.hour   * 60 + end.minute
            if te < ts: te += 1440
            for window in blocked_str.split(","):
                if "-" not in window: continue
                try:
                    ws_str = window.strip().split("-")[0]
                    we_str = window.strip().split("-")[1] if len(window.strip().split("-")) > 1 else ""
                    ws_m = time_to_minutes(ws_str.strip())
                    we_m = time_to_minutes(we_str.strip())
                    if we_m < ws_m: we_m += 1440
                    if not (ts >= we_m + 5 or te <= ws_m - 5):
                        blocked_role = emp_row.get("_blocked_role_" + window.strip(), "")
                        if role == "מפקח TSA" and "פיקוח" in blocked_role:
                            continue
                        return False
                except Exception:
                    pass

    is_tsa_inspector = (role == "מפקח TSA")
    new_terminal     = get_terminal(flight_gate or "")

    def to_m(dt): return dt.hour * 60 + dt.minute

    start_m = to_m(start)
    end_m   = to_m(end)
    if end_m < start_m: end_m += 1440

    for task in assignments:
        if task["עובד"] != emp_name:
            continue
        if clean_text(task.get("התחלה", "")) == "" or clean_text(task.get("סיום", "")) == "":
            continue

        es = to_datetime_time(task["התחלה"])
        ee = to_datetime_time(task["סיום"])
        es_m = to_m(es)
        ee_m = to_m(ee)
        if ee_m < es_m: ee_m += 1440

        buf = 5
        if not (start_m >= ee_m + buf or end_m <= es_m - buf):
            if is_tsa_inspector and task.get("תפקיד בסיס") == "מפקח TSA":
                existing_gate     = task.get("_gate", "")
                existing_terminal = get_terminal(existing_gate)
                if new_terminal and existing_terminal and new_terminal == existing_terminal:
                    continue
            return False

    return True


# =========================
# ASSIGNMENT ENGINE
# =========================

def count_all_tasks_local(assignments, emp_name):
    return sum(1 for task in assignments if task["עובד"] == emp_name)


def count_team_lead_tasks_local(assignments, emp_name):
    return sum(
        1 for task in assignments
        if task["עובד"] == emp_name and str(task["תפקיד"]).startswith("ראש צוות")
    )


def tasks_in_window_local(assignments, emp_name, window_start, window_end):
    from datetime import timedelta as _td
    buffer = _td(hours=3)
    count = 0
    for task in assignments:
        if task["עובד"] != emp_name:
            continue
        if clean_text(task.get("התחלה", "")) == "":
            continue
        try:
            ts = to_datetime_time(task["התחלה"])
            te = to_datetime_time(task["סיום"])
            if not (ts > window_end + buffer or te < window_start - buffer):
                count += 1
        except Exception:
            pass
    return count


def minutes_worked_since_shift_start(assignments, emp_name, emp, until_time_minutes):
    ss = clean_text(emp.get("תחילת משמרת", ""))
    if not is_time_text(ss):
        return 0
    shift_start_m = time_to_minutes(ss)
    total = 0
    for task in assignments:
        if task["עובד"] != emp_name:
            continue
        ts_str = clean_text(task.get("התחלה", ""))
        te_str = clean_text(task.get("סיום",   ""))
        if not ts_str or not te_str:
            continue
        try:
            ts = time_to_minutes(ts_str)
            te = time_to_minutes(te_str)
            if ts < shift_start_m: ts += 1440
            if te < shift_start_m: te += 1440
            if te < ts: te += 1440
            until = until_time_minutes
            if until < shift_start_m: until += 1440
            te_capped = min(te, until)
            if te_capped > ts:
                total += te_capped - ts
        except Exception:
            pass
    return total


def would_exceed_max_continuous(assignments, emp_name, emp, task_start, task_end):
    ss = clean_text(emp.get("תחילת משמרת", ""))
    if not is_time_text(ss):
        return False
    shift_start_m = time_to_minutes(ss)
    ts = task_start.hour * 60 + task_start.minute
    te = task_end.hour   * 60 + task_end.minute
    if ts < shift_start_m: ts += 1440
    if te < shift_start_m: te += 1440
    if te < ts: te += 1440
    worked = minutes_worked_since_shift_start(assignments, emp_name, emp, te)
    worked += (te - ts)
    return worked > MAX_CONTINUOUS_WORK_MINUTES


def night_break_window_passed(assignments, emp_name):
    tasks = sorted(
        [t for t in assignments if t.get("עובד") == emp_name and clean_text(t.get("סיום",""))],
        key=lambda t: time_to_minutes(clean_text(t.get("התחלה","00:00")))
    )
    for i in range(len(tasks) - 1):
        te_str = clean_text(tasks[i].get("סיום", ""))
        ts_str = clean_text(tasks[i+1].get("התחלה", ""))
        if not te_str or not ts_str: continue
        try:
            te = time_to_minutes(te_str)
            ts = time_to_minutes(ts_str)
            if ts < te: ts += 1440
            gap = ts - te
            te_in_window = NIGHT_BREAK_WINDOW_START <= (te % 1440) <= NIGHT_BREAK_WINDOW_END
            if gap >= 30 and te_in_window:
                return True
        except Exception:
            pass
    return False


def sort_candidates(candidates, assignments, role, task_start=None, task_end=None):
    from utils.helpers import area_switch_penalty, classify_shift

    candidates = candidates.copy()
    if candidates.empty:
        return candidates

    candidates["_area_penalty"] = candidates.apply(
        lambda row: area_switch_penalty(assignments, row, role), axis=1
    )
    candidates["_task_count"] = candidates["שם"].apply(
        lambda name: count_all_tasks_local(assignments, name)
    )

    if task_start and task_end:
        candidates["_nearby_tasks"] = candidates["שם"].apply(
            lambda name: -tasks_in_window_local(assignments, name, task_start, task_end)
        )
    else:
        candidates["_nearby_tasks"] = 0

    def shift_start_proximity(emp_row):
        if not task_start:
            return 0
        name = emp_row["שם"]
        if count_all_tasks_local(assignments, name) > 0:
            return 0
        ss = clean_text(emp_row.get("תחילת משמרת", ""))
        if not is_time_text(ss):
            return 9999
        s = time_to_minutes(ss)
        t = task_start.hour * 60 + task_start.minute
        if t < s:
            t += 1440
        return t - s

    candidates["_shift_proximity"] = candidates.apply(shift_start_proximity, axis=1)

    flight_before_130 = False
    if task_end:
        te_m = task_end.hour * 60 + task_end.minute
        flight_before_130 = (te_m <= LATE_SHIFT_END_MAX)

    def shift_priority(emp_row):
        if not flight_before_130:
            return 0
        sc = classify_shift(emp_row)
        return {"late": 0, "day": 1, "early_morning": 2, "night": 3, "unknown": 4}.get(sc, 4)

    candidates["_shift_priority"] = candidates.apply(shift_priority, axis=1)

    def dual_qual_score(emp_row):
        is_tsa = str(emp_row.get("מפקח TSA", emp_row.get("מפקח tsa", ""))).strip() == "כן"
        is_tl  = str(emp_row.get("ראש צוות", "")).strip() == "כן"
        if is_tsa and is_tl:
            if role == "מפקח TSA":  return 0
            if role == "ראש צוות": return 1
        return 0

    candidates["_dual_qual"] = candidates.apply(dual_qual_score, axis=1)

    sort_cols_base = ["_dual_qual", "_shift_priority", "_area_penalty", "_nearby_tasks", "_shift_proximity", "_task_count"]

    if role == "ראש צוות":
        candidates["_role_count"] = candidates["שם"].apply(
            lambda name: count_team_lead_tasks_local(assignments, name)
        )
        return candidates.sort_values(
            ["_dual_qual", "_shift_priority", "_area_penalty", "_nearby_tasks", "_shift_proximity", "_role_count", "_task_count"]
        )

    if role == "דייל":
        candidates["_role_fit"] = candidates.apply(
            lambda row: 0 if str(row.get("ראש צוות", "")).strip() == "כן" else 1, axis=1
        )
        return candidates.sort_values(
            ["_dual_qual", "_shift_priority", "_area_penalty", "_nearby_tasks", "_shift_proximity", "_role_fit", "_task_count"]
        )

    return candidates.sort_values(sort_cols_base)


def has_required_mentor(assignments_for_flight, employees_df, training_type):
    required_col = "מסמיך רצים" if training_type == "הסמכה" else "חונך רצים"
    for task in assignments_for_flight:
        if str(task["תפקיד"]).startswith("ראש צוות") and "❌" not in str(task["עובד"]):
            emp = employees_df[employees_df["שם"] == task["עובד"]]
            if not emp.empty and str(emp.iloc[0].get(required_col, "")).strip() == "כן":
                return True
    return False


def has_trainee_available(employees_df):
    if "טרייני רצ" not in employees_df.columns:
        return False
    return (employees_df["טרייני רצ"].astype(str).str.strip() == "כן").any()


def flight_has_mentor_teamlead(assignments_for_flight, employees_df, training_type):
    required_cols = ["חונך רצים", "מסמיך רצים"]
    if clean_text(training_type) == "הסמכה":
        required_cols = ["מסמיך רצים"]

    for task in assignments_for_flight:
        if not str(task.get("תפקיד", "")).startswith("ראש צוות"):
            continue
        worker = str(task.get("עובד", ""))
        if "❌" in worker:
            continue
        emp = employees_df[employees_df["שם"] == worker]
        if emp.empty:
            continue
        row = emp.iloc[0]
        for col in required_cols:
            if str(row.get(col, "")).strip() == "כן":
                return True
    return False


def trainee_already_used(assignments):
    for task in assignments:
        if str(task.get("תפקיד בסיס", "")) == "טרייני רצ" and "❌" not in str(task.get("עובד", "")):
            return True
    return False


def _try_select(candidates, assignments, role, start, end, flight_gate,
                check_break=True, check_continuous=True):
    """
    Scan candidates in order and return the first available name, or None.
    Relaxes constraints progressively:
      Pass 1 (default): break room + continuous-work limit
      Pass 2: break room only
      Pass 3: availability only
    """
    for _, emp in candidates.iterrows():
        name = emp["שם"]
        if not is_within_shift(emp, start, end):
            continue
        if not is_available(assignments, name, start, end, emp,
                            role=role, flight_gate=flight_gate):
            continue
        if check_break and not has_room_for_break(assignments, emp, name, start, end):
            continue
        if check_continuous and would_exceed_max_continuous(assignments, name, emp, start, end):
            continue
        return name
    return None


def build_schedule(flights_df, employees_df):
    assignments = []
    flights_df = flights_df.copy()
    flights_df["_flight_key"] = flights_df["טיסה"].apply(
        lambda v: clean_text(v).upper().replace(" ", "")
    )
    flights_df = flights_df.drop_duplicates(subset=["_flight_key"], keep="first").drop(columns=["_flight_key"])

    for _, flight in flights_df.iterrows():
        if clean_text(flight.get("המראה", "")) == "":
            continue

        req = get_requirements(flight)
        used_on_flight = set()
        assignments_for_flight = []

        trainee_needed = req.get("טרייני רצ", 0) > 0
        training_type = clean_text(flight.get("סוג הכשרה", "חניכה")) or "חניכה"

        for role in ROLE_ORDER:
            amount = req.get(role, 0)

            for i in range(amount):
                start = role_start_time(flight, role)
                end   = role_end_time(flight)

                role_col = role
                if role not in employees_df.columns:
                    role_col = next(
                        (c for c in employees_df.columns if clean_text(c).upper() == clean_text(role).upper()),
                        None
                    )
                if not role_col or role_col not in employees_df.columns:
                    candidates = employees_df.iloc[0:0].copy()
                else:
                    candidates = employees_df[
                        (employees_df[role_col].astype(str).str.strip() == "כן") &
                        (~employees_df["_name_key"].isin(used_on_flight))
                    ].copy()

                if role == "ראש צוות" and trainee_needed:
                    mentor_col = "מסמיך רצים" if training_type == "הסמכה" else "חונך רצים"
                    if mentor_col not in candidates.columns:
                        candidates[mentor_col] = "לא"
                    mentors = candidates[candidates[mentor_col].astype(str).str.strip() == "כן"]
                    if not mentors.empty:
                        candidates = mentors

                candidates = sort_candidates(candidates, assignments, role, start, end)

                gate = clean_text(flight.get("גייט", ""))
                selected = (
                    _try_select(candidates, assignments, role, start, end, gate) or
                    _try_select(candidates, assignments, role, start, end, gate,
                                check_continuous=False) or
                    _try_select(candidates, assignments, role, start, end, gate,
                                check_break=False, check_continuous=False)
                )

                if selected:
                    worker = selected
                    reason = "שובץ כי העובד מוסמך לתפקיד, פנוי בזמן המשימה וללא חפיפה"
                    used_on_flight.add(name_key(selected))
                else:
                    worker = f"❌ חסר {role}"
                    reason = "לא נמצא עובד מתאים: אין זמינות, יש חפיפה או שחסרה הסמכה"

                task = {
                    "טיסה":       flight["טיסה"],
                    "יעד":        flight["יעד"],
                    "תפקיד":      role if amount == 1 else f"{role} {i+1}",
                    "תפקיד בסיס": role,
                    "עובד":       worker,
                    "התחלה":      start.strftime("%H:%M"),
                    "סיום":       end.strftime("%H:%M"),
                    "_gate":      gate,
                    "סיבה":       reason,
                }
                assignments.append(task)
                assignments_for_flight.append(task)

        # טרייני ר״צ
        if (
            has_trainee_available(employees_df)
            and flight_has_mentor_teamlead(assignments_for_flight, employees_df, training_type)
        ):
            role  = "טרייני רצ"
            start = role_start_time(flight, role)
            end   = role_end_time(flight)

            role_col_t = role if role in employees_df.columns else next(
                (c for c in employees_df.columns if clean_text(c).upper() == clean_text(role).upper()), None
            )
            if not role_col_t:
                candidates = employees_df.iloc[0:0].copy()
            else:
                candidates = employees_df[
                    (employees_df[role_col_t].astype(str).str.strip() == "כן") &
                    (~employees_df["_name_key"].isin(used_on_flight))
                ].copy()

            candidates = sort_candidates(candidates, assignments, role, start, end)

            gate = clean_text(flight.get("גייט", ""))
            selected = (
                _try_select(candidates, assignments, role, start, end, gate) or
                _try_select(candidates, assignments, role, start, end, gate,
                            check_continuous=False) or
                _try_select(candidates, assignments, role, start, end, gate,
                            check_break=False, check_continuous=False)
            )

            if selected:
                task = {
                    "טיסה":       flight["טיסה"],
                    "יעד":        flight["יעד"],
                    "תפקיד":      "טרייני ר״צ",
                    "תפקיד בסיס": "טרייני רצ",
                    "עובד":       selected,
                    "התחלה":      start.strftime("%H:%M"),
                    "סיום":       end.strftime("%H:%M"),
                }
                assignments.append(task)
                assignments_for_flight.append(task)
                used_on_flight.add(name_key(selected))

    return pd.DataFrame(assignments)


def upgrade_teamleads(assignments_df, employees_df):
    """
    Second pass: for each missing ראש צוות slot, check if a qualified TL
    is assigned as דייל on a concurrent flight. If so, promote them.
    """
    assignments = assignments_df.to_dict("records")

    def tasks_overlap(t1, t2):
        try:
            s1 = time_to_minutes(t1["התחלה"]); e1 = time_to_minutes(t1["סיום"])
            s2 = time_to_minutes(t2["התחלה"]); e2 = time_to_minutes(t2["סיום"])
            if e1 < s1: e1 += 1440
            if e2 < s2: e2 += 1440
            if s2 < s1 - 720: s2 += 1440; e2 += 1440
            if s1 < s2 - 720: s1 += 1440; e1 += 1440
            return not (e1 <= s2 + 5 or e2 <= s1 + 5)
        except Exception:
            return False

    changed = True
    max_iter = 20
    while changed and max_iter > 0:
        changed = False
        max_iter -= 1

        missing_tl = [t for t in assignments if "❌" in str(t.get("עובד","")) and t.get("תפקיד בסיס") == "ראש צוות"]
        if not missing_tl:
            break

        for missing in missing_tl:
            tl_as_agent = [
                t for t in assignments
                if t.get("תפקיד בסיס") == "דייל"
                and "❌" not in str(t.get("עובד",""))
                and tasks_overlap(t, missing)
            ]
            promoted = None
            promoted_task = None
            for t in tl_as_agent:
                worker_name = t["עובד"]
                emp_row = employees_df[employees_df["שם"] == worker_name]
                if emp_row.empty:
                    continue
                if str(emp_row.iloc[0].get("ראש צוות","")).strip() == "כן":
                    promoted = worker_name
                    promoted_task = t
                    break

            if not promoted:
                continue

            used_names = set(t["עובד"] for t in assignments if "❌" not in str(t.get("עובד","")))
            used_names.discard(promoted)

            agent_start = to_datetime_time(promoted_task["התחלה"])
            agent_end   = to_datetime_time(promoted_task["סיום"])

            agent_candidates = employees_df[
                (employees_df["דייל"].astype(str).str.strip() == "כן") &
                (~employees_df["שם"].isin(used_names))
            ].copy()
            agent_candidates = sort_candidates(agent_candidates, assignments, "דייל", agent_start, agent_end)

            replacement = None
            for _, emp in agent_candidates.iterrows():
                name = emp["שם"]
                if (
                    is_within_shift(emp, agent_start, agent_end)
                    and is_available(assignments, name, agent_start, agent_end, emp)
                    and has_room_for_break(assignments, emp, name, agent_start, agent_end)
                ):
                    replacement = name
                    break

            missing["עובד"] = promoted
            promoted_task["עובד"] = replacement if replacement else "❌ חסר דייל"
            changed = True
            break

    return pd.DataFrame(assignments)


# =========================
# SWAP HELPERS
# =========================

def get_qualified_candidates_for_swap(schedule_df, employees_df, flight_num, role_base, task_idx):
    task_row = schedule_df.loc[task_idx]
    start_str = str(task_row.get("התחלה", ""))
    end_str   = str(task_row.get("סיום",   ""))
    current_worker = str(task_row.get("עובד", ""))

    role_col_map = {
        "ראש צוות":   "ראש צוות",
        "דייל":       "דייל",
        "מתאם תורים": "מתאם תורים",
        "מפקח TSA":   "מפקח TSA",
        "שומר TSA":   "שומר TSA",
        "טרייני רצ":  "טרייני רצ",
        "טרייני ר״צ": "טרייני רצ",
    }
    col = role_col_map.get(normalize_role_label(role_base), role_base)

    if col not in employees_df.columns:
        return []

    certified = employees_df[employees_df[col].astype(str).str.strip() == "כן"].copy()

    if not is_time_text(start_str) or not is_time_text(end_str):
        return [n for n in certified["שם"].tolist() if n != current_worker]

    try:
        task_start = to_datetime_time(start_str)
        task_end   = to_datetime_time(end_str)
    except Exception:
        return []

    other_tasks = schedule_df[schedule_df.index != task_idx].copy()
    other_tasks = other_tasks[other_tasks["התחלה"].astype(str).str.strip() != ""]

    results = []
    for _, emp_row in certified.iterrows():
        name = emp_row["שם"]
        if name == current_worker:
            continue
        if not is_within_shift(emp_row, task_start, task_end):
            continue
        person_tasks = other_tasks[other_tasks["עובד"].astype(str) == name]
        conflict = False
        from datetime import timedelta as _td
        buffer = _td(minutes=5)
        for _, pt in person_tasks.iterrows():
            try:
                ps = to_datetime_time(str(pt["התחלה"]))
                pe = to_datetime_time(str(pt["סיום"]))
                if not (task_start >= pe + buffer or task_end <= ps - buffer):
                    conflict = True
                    break
            except Exception:
                pass
        if not conflict:
            results.append(name)

    return results


def do_swap(schedule_df, task_idx, new_worker, displaced_action, displaced_target_flight=None):
    df = schedule_df.copy()
    old_worker = str(df.at[task_idx, "עובד"])
    df.at[task_idx, "עובד"] = new_worker

    if displaced_action == "move" and displaced_target_flight:
        role_base = str(df.at[task_idx, "תפקיד בסיס"])
        target_mask = (
            (df["טיסה"].astype(str).str.strip() == displaced_target_flight.strip()) &
            (df["תפקיד בסיס"].astype(str) == role_base) &
            (df["עובד"].astype(str).str.contains("❌"))
        )
        target_slots = df[target_mask]
        if not target_slots.empty:
            first_slot = target_slots.index[0]
            df.at[first_slot, "עובד"] = old_worker

    return df
