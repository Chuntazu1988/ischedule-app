import re
import pandas as pd

from utils.constants import ROLE_COLUMNS
from utils.helpers import (
    clean_text, normalize_yes_no, normalize_time_text, clean_roster_name,
    extract_shift_range_from_text, is_time_text, parse_times, safe_sort_by_time,
    find_column, flight_key, name_key, name_key_reversed,
)


# =========================
# SHIFT MAP FROM EXCEL
# =========================

def build_shift_map_from_excel(uploaded_file):
    """
    Scan the workbook and extract per-employee:
      - shift start/end
      - modified shift window
      - blocked time windows
      - unavailable flag (SICK)
      - early end

    Returns dict: name_key -> {
        "start": HH:MM, "end": HH:MM, "original": str,
        "blocked": [(start, end), ...],
        "sick": bool,
        "shift_end_override": HH:MM or None,
        "shift_start_override": HH:MM or None,
    }
    """
    shift_map = {}
    TIME_RANGE_RE  = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    SINGLE_TIME_RE = re.compile(r"(\d{1,2}:\d{2})")

    BLOCKED_KEYWORDS = ["בידוק", "מתדרכ", "ועדת היגוי", "רענון tsa", "רענון", "77"]
    SICK_KEYWORDS    = ["sick", "מחלה"]
    END_KEYWORDS     = ["עד ", "עד:"]
    START_KEYWORDS   = ["מש' מ", "מש מ", "משמרת מ"]
    END_SHIFT_KW     = ["מש' עד", "מש עד", "משמרת עד", "מש'"]

    def is_blocked_label(text):
        tl = text.lower()
        return any(kw in tl for kw in BLOCKED_KEYWORDS)

    def is_sick(text):
        tl = text.lower()
        return any(kw in tl for kw in SICK_KEYWORDS)

    try:
        uploaded_file.seek(0)
        sheets = pd.read_excel(uploaded_file, sheet_name=None, header=None, dtype=str)
    except Exception:
        return shift_map

    for sheet_name, raw in sheets.items():
        for col in raw.columns:
            current_start = ""
            current_end   = ""
            current_blocked_range = None
            current_blocked_label = ""

            for row_i, cell in raw[col].items():
                cell_text = clean_text(cell)
                if not cell_text:
                    continue

                # Special inline format: "NAME-תגבור בין HH:MM-HH:MM"
                is_availability_note = ('תגבור' in cell_text or 'ואז בין' in cell_text)
                if is_availability_note:
                    dash_idx = cell_text.find('-')
                    name_part = cell_text[:dash_idx].strip() if dash_idx > 0 else cell_text
                    pn = clean_roster_name(name_part) if len(name_part.split()) >= 2 else name_part.strip()
                    if pn and current_start and current_end:
                        key = name_key(pn)
                        avail_windows = TIME_RANGE_RE.findall(cell_text)
                        entry = shift_map.get(key, {
                            "start":    current_start,
                            "end":      current_end,
                            "original": pn,
                            "blocked":  [],
                            "sick":     False,
                            "shift_end_override":   None,
                            "shift_start_override": None,
                            "available_windows": [],
                        })
                        if avail_windows:
                            entry["available_windows"] = [(normalize_time_text(ws), normalize_time_text(we)) for ws, we in avail_windows]
                        shift_map[key] = entry
                    continue

                m = TIME_RANGE_RE.search(cell_text)
                if m:
                    s = normalize_time_text(m.group(1))
                    e = normalize_time_text(m.group(2))
                    if is_blocked_label(cell_text):
                        current_blocked_range = (s, e)
                        current_blocked_label = cell_text
                        current_start = s
                        current_end   = e
                    else:
                        current_start = s
                        current_end   = e
                        current_blocked_range = None
                        current_blocked_label = ""
                    continue

                if not current_start or not current_end:
                    continue

                possible_name = clean_roster_name(cell_text)
                if not possible_name:
                    continue

                key = name_key(possible_name)

                sick            = is_sick(cell_text)
                shift_end_ovr   = None
                shift_start_ovr = None
                extra_blocked   = []

                for kw in END_SHIFT_KW:
                    if kw in cell_text:
                        mt = SINGLE_TIME_RE.search(cell_text[cell_text.find(kw):])
                        if mt:
                            shift_end_ovr = normalize_time_text(mt.group(1))
                        break

                if not shift_end_ovr:
                    for kw in END_KEYWORDS:
                        if kw in cell_text and kw not in END_SHIFT_KW:
                            mt = SINGLE_TIME_RE.search(cell_text[cell_text.find(kw):])
                            if mt:
                                shift_end_ovr = normalize_time_text(mt.group(1))
                            break

                for kw in START_KEYWORDS:
                    if kw in cell_text:
                        mt = SINGLE_TIME_RE.search(cell_text[cell_text.find(kw):])
                        if mt:
                            shift_start_ovr = normalize_time_text(mt.group(1))
                        break

                inline_ranges = TIME_RANGE_RE.findall(cell_text)
                for ws, we in inline_ranges:
                    ws_n = normalize_time_text(ws)
                    we_n = normalize_time_text(we)
                    if is_blocked_label(cell_text) and (ws_n, we_n) != (current_start, current_end):
                        extra_blocked.append((ws_n, we_n))

                if key not in shift_map:
                    shift_map[key] = {
                        "start":    current_start,
                        "end":      current_end,
                        "original": possible_name,
                        "blocked":       [],
                        "blocked_roles": [],
                        "sick":     False,
                        "shift_end_override":   None,
                        "shift_start_override": None,
                    }
                    key_rev = name_key(" ".join(reversed(possible_name.split())))
                    if key_rev not in shift_map:
                        shift_map[key_rev] = shift_map[key]
                    # שמות עם שם אמצעי (3+ מילים): הוסף מפתחות ללא השם האמצעי
                    # כדי לזהות עובדים שרשומים בקובץ העובדים עם שם ומשפחה בלבד
                    _words = possible_name.split()
                    if len(_words) >= 3:
                        _first, _last = _words[0], _words[-1]
                        for _combo in [f"{_first} {_last}", f"{_last} {_first}"]:
                            _k = name_key(_combo)
                            if _k not in shift_map:
                                shift_map[_k] = shift_map[key]

                entry = shift_map[key]
                if sick:
                    entry["sick"] = True
                if shift_end_ovr and not entry["shift_end_override"]:
                    entry["shift_end_override"] = shift_end_ovr
                if shift_start_ovr and not entry["shift_start_override"]:
                    entry["shift_start_override"] = shift_start_ovr
                if current_blocked_range:
                    if current_blocked_range not in entry["blocked"]:
                        entry["blocked"].append(current_blocked_range)
                        entry.setdefault("blocked_roles", []).append(current_blocked_label)
                for eb in extra_blocked:
                    if eb not in entry["blocked"]:
                        entry["blocked"].append(eb)
                        entry.setdefault("blocked_roles", []).append("")

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    return shift_map


def apply_shift_map_to_employees(employees_df, shift_map_with_names):
    """
    Apply shift times and annotations from the daily schedule to employees_df.
    Adds columns: תחילת משמרת, סוף משמרת, חסימות, חולה
    """
    df = employees_df.copy()

    for col in ["תחילת משמרת", "סוף משמרת", "חסימות", "חולה"]:
        if col not in df.columns:
            df[col] = "" if col != "חולה" else False

    def get_entry(emp_name):
        key = name_key(emp_name)
        if key in shift_map_with_names:
            return shift_map_with_names[key]
        key_rev = name_key_reversed(emp_name)
        if key_rev in shift_map_with_names:
            return shift_map_with_names[key_rev]
        parts = {name_key(w) for w in emp_name.split() if len(w) > 1}
        best = None; best_score = 1
        for _, entry in shift_map_with_names.items():
            orig_parts = {name_key(w) for w in entry["original"].split() if len(w) > 1}
            shared = len(parts & orig_parts)
            if shared > best_score:
                best_score = shared; best = entry
        return best

    for idx, row in df.iterrows():
        emp_name = clean_text(row.get("שם", ""))
        if not emp_name:
            continue
        if clean_text(df.at[idx, "תחילת משמרת"]):
            continue  # already set

        entry = get_entry(emp_name)
        if not entry:
            continue

        if entry.get("sick"):
            df.at[idx, "חולה"] = True
            continue

        start = entry.get("shift_start_override") or entry["start"]
        end   = entry.get("shift_end_override")   or entry["end"]

        df.at[idx, "תחילת משמרת"] = start
        df.at[idx, "סוף משמרת"]   = end

        blocked = entry.get("blocked", [])
        blocked_roles = entry.get("blocked_roles", [])
        if blocked:
            df.at[idx, "חסימות"] = ",".join(f"{s}-{e}" for s, e in blocked)
            for i, (s, e) in enumerate(blocked):
                role_label = blocked_roles[i] if i < len(blocked_roles) else ""
                df.at[idx, f"_blocked_role_{s}-{e}"] = role_label

        avail = entry.get("available_windows", [])
        if avail:
            if "זמינות" not in df.columns:
                df["זמינות"] = ""
            df.at[idx, "זמינות"] = ",".join(f"{s}-{e}" for s, e in avail)

    return df


# =========================
# LOAD FILES
# =========================

def load_daily_schedule(uploaded_file):
    excel = pd.ExcelFile(uploaded_file)
    sheet_name = "דוח שיבוץ טיסות - המראות" if "דוח שיבוץ טיסות - המראות" in excel.sheet_names else excel.sheet_names[0]
    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name)
    raw.columns = raw.columns.astype(str).str.strip()

    flights = []

    if {"Unnamed: 8", "Unnamed: 7", "Unnamed: 6"}.issubset(set(raw.columns)):
        for _, row in raw.iterrows():
            flight = row.get("Unnamed: 8")
            time_text = row.get("Unnamed: 7")
            destination = row.get("Unnamed: 6")
            aircraft = row.get("Unnamed: 5")

            flight_text = clean_text(flight)
            if not flight_text.startswith("LY"):
                continue
            flight_num = flight_text.replace("LY", "").strip()
            if flight_num.startswith("8"):
                continue

            departure, boarding = parse_times(time_text)

            flights.append({
                "טיסה": flight_text,
                "יעד": clean_text(destination).upper(),
                "המראה": departure,
                "בורדינג": boarding,
                "גייט": "",
                "סוג מטוס": clean_text(aircraft),
                "רישוי": "",
                "נוסעים": "",
                "טרייני רצ": "לא",
                "סוג הכשרה": "",
            })
    else:
        flight_col   = find_column(raw, ["טיסה", "מספר טיסה", "Flight", "flight"])
        dest_col     = find_column(raw, ["יעד", "Destination", "destination"])
        dep_col      = find_column(raw, ["המראה", "זמן המראה", "Departure", "departure"])
        board_col    = find_column(raw, ["בורדינג", "תחילת בורדינג", "Boarding", "boarding"])
        gate_col     = find_column(raw, ["גייט", "שער", "Gate", "gate"])
        aircraft_col = find_column(raw, ["סוג מטוס", "מטוס", "Aircraft", "aircraft"])
        reg_col      = find_column(raw, ["רישוי", "רישום", "Registration", "registration"])
        pax_col      = find_column(raw, ["נוסעים", "PAX", "pax"])
        trainee_col  = find_column(raw, ["טרייני רצ", "טרייני ר״צ", 'טרייני ר"צ'])
        training_col = find_column(raw, ["סוג הכשרה", "הכשרה"])

        if not flight_col:
            raise ValueError("לא נמצאה עמודת טיסה בקובץ הסידור")

        for _, row in raw.iterrows():
            flight_text = clean_text(row.get(flight_col))
            if not flight_text.startswith("LY"):
                continue
            if flight_text.replace("LY", "").strip().startswith("8"):
                continue

            dep = clean_text(row.get(dep_col)) if dep_col else ""
            boarding = clean_text(row.get(board_col)) if board_col else ""

            if not is_time_text(dep):
                dep, parsed_boarding = parse_times(dep)
                if not boarding:
                    boarding = parsed_boarding

            flights.append({
                "טיסה": flight_text,
                "יעד": clean_text(row.get(dest_col)).upper() if dest_col else "",
                "המראה": dep,
                "בורדינג": boarding,
                "גייט": clean_text(row.get(gate_col)) if gate_col else "",
                "סוג מטוס": clean_text(row.get(aircraft_col)) if aircraft_col else "",
                "רישוי": clean_text(row.get(reg_col)) if reg_col else "",
                "נוסעים": clean_text(row.get(pax_col)) if pax_col else "",
                "טרייני רצ": normalize_yes_no(row.get(trainee_col)) if trainee_col else "לא",
                "סוג הכשרה": clean_text(row.get(training_col)) if training_col else "",
            })

    flights_df = pd.DataFrame(flights)

    if flights_df.empty:
        return pd.DataFrame(columns=[
            "טיסה", "יעד", "המראה", "בורדינג", "גייט", "סוג מטוס", "רישוי", "נוסעים", "טרייני רצ", "סוג הכשרה"
        ])

    flights_df["_flight_key"] = flights_df["טיסה"].apply(flight_key)
    flights_df = flights_df.drop_duplicates(subset=["_flight_key"], keep="first").drop(columns=["_flight_key"])
    flights_df = flights_df[flights_df["המראה"].astype(str).str.strip() != ""].copy()
    flights_df = safe_sort_by_time(flights_df, "המראה")

    return flights_df


def normalize_employees(df):
    df = df.copy()
    df.columns = (
    df.columns.astype(str)
    .str.replace("\ufeff", "", regex=False)
    .str.replace("\u200f", "", regex=False)
    .str.replace("\u200e", "", regex=False)
    .str.strip()
)

    if "שם" not in df.columns:
        raise ValueError("בקובץ העובדים חייבת להיות עמודה בשם: שם")

    aliases = {
        "מפקח tsa":        "מפקח TSA",
        "מפקח Tsa":        "מפקח TSA",
        "פיקוח tsa":       "מפקח TSA",
        "פיקוח TSA":       "מפקח TSA",
        "פיקוח Tsa":       "מפקח TSA",
        "שומר tsa":        "שומר TSA",
        "שומר Tsa":        "שומר TSA",
        "טרייני ר״צ":      "טרייני רצ",
        'טרייני ר"צ':      "טרייני רצ",
        "ראש צוות חונך":   "חונך רצים",
        "ראש צוות מסמיך":  "מסמיך רצים",
        "ראש צוות מסמיך ": "מסמיך רצים",
        "טרייני ר״צ ":     "טרייני רצ",
    }

    for old, new in aliases.items():
        if old in df.columns:
            if new not in df.columns:
                df[new] = df[old]
            else:
                df[new] = df[new].apply(clean_text)
                df[old] = df[old].apply(clean_text)
                mask = df[new].str.strip().isin(["", "לא"]) & (df[old] != "")
                df.loc[mask, new] = df.loc[mask, old]

    df["שם"] = df["שם"].apply(clean_text)
    df = df[df["שם"] != ""].copy()
    df["_name_key"] = df["שם"].apply(name_key)

    for col in ROLE_COLUMNS:
        if col not in df.columns:
            df[col] = "לא"
        df[col] = df[col].apply(normalize_yes_no)

    for col in ["תחילת משמרת", "סוף משמרת", "חסימות", "זמינות"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(clean_text)

    if "חולה" not in df.columns:
        df["חולה"] = False

    def to_bool_sick(v):
        if isinstance(v, bool): return v
        s = str(v).strip().lower()
        return s in {"true", "1", "כן", "yes"}
    df["חולה"] = df["חולה"].apply(to_bool_sick)

    if "זמינות" not in df.columns:
        df["זמינות"] = ""

    def clean_avail(v):
        import re as _re
        s = str(v).strip() if not pd.isna(v) else ""
        if not s or s.lower() in {"false", "true", "none", "nan", "0", "1"}:
            return ""
        if not _re.search(r'\d{1,2}:\d{2}', s):
            return ""
        return s
    df["זמינות"] = df["זמינות"].apply(clean_avail)

    # נרמל כפילויות —
    # _dedup_key: מילות השם ממוינות, כך ש"שני פדידה" ו"פדידה שני" מקבלות אותו מפתח.
    # לשמות עם שם אמצעי (3+ מילים): נשתמש רק בשם הראשון והאחרון לצורך הדה-דופ,
    # כך ש"טליה חנה טטרואשוילי" ו"טטרואשוילי טליה" מזוהות כאותו עובד.
    def _dedup_key(full_name: str) -> str:
        parts = [name_key(w) for w in full_name.split() if len(w) > 1]
        if len(parts) >= 3:
            parts = [parts[0], parts[-1]]
        return "".join(sorted(parts))

    df["_name_key"] = df["שם"].apply(name_key)
    df["_dedup_key"] = df["שם"].apply(_dedup_key)
    df = df.drop_duplicates(subset=["_dedup_key"], keep="first").reset_index(drop=True)
    df = df.drop(columns=["_dedup_key"])

    return df
