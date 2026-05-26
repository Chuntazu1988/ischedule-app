import re
import pandas as pd
def normalize_yes_no(value):
    if value is None:
        return "לא"

    text = str(value).strip().lower()

    yes_values = [
        "כן",
        "yes",
        "true",
        "1",
        "y",
        "x",
    ]

    return "כן" if text in yes_values else "לא"
try:
    from constants import ROLE_COLUMNS
except ModuleNotFoundError:
    ROLE_COLUMNS = [
    "אחמ״ש",
    "אחמש",
    "דלפק",
    "שער",
    "בידוק",
    "תורן",
    "מפעיל",
    "משמרת",
    "תפקיד",
]
def flight_key(value):
    if value is None:
        return ""

    text = str(value).strip().upper()

    text = text.replace(" ", "")
    text = text.replace("-", "")

    return text
def name_key(value):
    if value is None:
        return ""

    text = str(value).strip().lower()

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")

    return text
def name_key_reversed(value):
    if value is None:
        return ""

    text = str(value).strip()

    parts = text.split()

    if len(parts) < 2:
        return name_key(text)

    reversed_text = " ".join(reversed(parts))

    return name_key(reversed_text)
def clean_roster_name(value):
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() == "nan":
        return ""

    text = text.replace("\n", " ")
    text = text.replace("  ", " ")

    return text.strip()
def safe_sort_by_time(df, column_name):
    if column_name not in df.columns:
        return df

    try:
        return df.sort_values(
            by=column_name,
            key=lambda col: col.astype(str)
        ).reset_index(drop=True)

    except Exception:
        return df
def normalize_time_text(value):
    if value is None:
        return ""

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return ""

    text = text.replace(".", ":")

    if ":" in text:
        parts = text.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            return text

    try:
        hour = int(float(text))
        return f"{hour:02d}:00"
    except Exception:
        return text
def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def safe_str(value):
    if value is None:
        return ""
    return str(value)


def is_time_like(value):
    text = str(value)
    return ":" in text


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


def _normalize_flight_cell(value):
    """Return a clean LY flight number from almost any cell text."""
    text = clean_text(value).upper().replace("‏", "").replace("‎", "")
    text = re.sub(r"\s+", "", text)
    m = re.search(r"LY\d{1,4}[A-Z]?", text)
    if not m:
        return ""
    flight = m.group(0)
    # לא מייבאים טיסות 8XXX, לפי החוק שקבענו
    if flight.replace("LY", "").startswith("8"):
        return ""
    return flight


def _normalize_time_cell(value):
    """Return HH:MM from strings / Excel times / pandas timestamps."""
    if pd.isna(value):
        return ""

    # pandas / python datetime-like values
    try:
        if hasattr(value, "hour") and hasattr(value, "minute"):
            return f"{int(value.hour):02d}:{int(value.minute):02d}"
    except Exception:
        pass

    text = clean_text(value)
    if not text:
        return ""

    # Excel sometimes stores time as fraction of day
    try:
        if re.fullmatch(r"\d+(\.\d+)?", text):
            num = float(text)
            if 0 <= num < 1:
                total = round(num * 24 * 60)
                return f"{(total // 60) % 24:02d}:{total % 60:02d}"
    except Exception:
        pass

    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def _parse_time_pair(value):
    """Return departure and boarding if the same cell contains one or two times."""
    text = clean_text(value)
    times = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", text)
    times = [_normalize_time_cell(t) for t in times]
    times = [t for t in times if t]
    if len(times) >= 2:
        return times[0], times[1]
    if len(times) == 1:
        return times[0], ""
    return _normalize_time_cell(value), ""


def _first_existing_column(df, names):
    """Find a column by exact name or case-insensitive name."""
    by_clean = {clean_text(c): c for c in df.columns}
    by_lower = {clean_text(c).lower(): c for c in df.columns}
    for name in names:
        if name in by_clean:
            return by_clean[name]
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return None


def _value_from_nearby_row(row_values, start_index, preferred_offsets):
    """Pick the first non-empty value around a detected flight cell."""
    for off in preferred_offsets:
        i = start_index + off
        if 0 <= i < len(row_values):
            val = clean_text(row_values[i])
            if val:
                return val
    return ""


def load_daily_schedule(uploaded_file):
    """
    Load the daily flight roster from the work schedule file.

    Works with:
    1. The official Hebrew sheet: דוח שיבוץ טיסות - המראות
    2. A clean table with headers like טיסה / יעד / המראה / בורדינג
    3. A messy Excel export where the useful columns are Unnamed: 8/7/6
    4. A raw grid where the flight number appears somewhere in the row
    """
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    excel = pd.ExcelFile(uploaded_file)
    preferred_sheet = "דוח שיבוץ טיסות - המראות"
    sheet_name = preferred_sheet if preferred_sheet in excel.sheet_names else excel.sheet_names[0]

    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, dtype=object)
    raw.columns = raw.columns.astype(str).str.strip()

    flights = []

    def add_flight(flight_text, destination="", departure="", boarding="", gate="", aircraft="", reg="", pax="", trainee="לא", training=""):
        flight_text = _normalize_flight_cell(flight_text)
        if not flight_text:
            return

        dep, parsed_boarding = _parse_time_pair(departure)
        boarding_norm = _normalize_time_cell(boarding) or parsed_boarding

        # If the boarding column accidentally contains two times, use the first one there
        if not boarding_norm:
            _, b2 = _parse_time_pair(boarding)
            boarding_norm = b2

        if not dep:
            return

        flights.append({
            "טיסה": flight_text,
            "יעד": clean_text(destination).upper(),
            "המראה": dep,
            "בורדינג": boarding_norm,
            "גייט": clean_text(gate),
            "סוג מטוס": clean_text(aircraft),
            "רישוי": clean_text(reg),
            "נוסעים": clean_text(pax),
            "טרייני רצ": normalize_yes_no(trainee),
            "סוג הכשרה": clean_text(training),
        })

    # Case 1: the known export layout, where flight/time/destination sit in Unnamed columns
    if {"Unnamed: 8", "Unnamed: 7", "Unnamed: 6"}.issubset(set(raw.columns)):
        for _, row in raw.iterrows():
            add_flight(
                row.get("Unnamed: 8"),
                destination=row.get("Unnamed: 6"),
                departure=row.get("Unnamed: 7"),
                aircraft=row.get("Unnamed: 5"),
            )

    # Case 2: clean headers
    if not flights:
        flight_col   = _first_existing_column(raw, ["טיסה", "מספר טיסה", "Flight", "FlightNo", "flight", "flightno"])
        dest_col     = _first_existing_column(raw, ["יעד", "Destination", "destination", "Dest", "dest"])
        dep_col      = _first_existing_column(raw, ["המראה", "זמן המראה", "Departure", "STD", "departure", "std"])
        board_col    = _first_existing_column(raw, ["בורדינג", "תחילת בורדינג", "Boarding", "boarding"])
        gate_col     = _first_existing_column(raw, ["גייט", "שער", "Gate", "gate"])
        aircraft_col = _first_existing_column(raw, ["סוג מטוס", "מטוס", "Aircraft", "aircraft", "A/C", "AC"])
        reg_col      = _first_existing_column(raw, ["רישוי", "רישום", "Registration", "registration", "Reg", "REG"])
        pax_col      = _first_existing_column(raw, ["נוסעים", "PAX", "pax", "Passengers", "passengers"])
        trainee_col  = _first_existing_column(raw, ["טרייני רצ", "טרייני ר״צ", 'טרייני ר"צ'])
        training_col = _first_existing_column(raw, ["סוג הכשרה", "הכשרה"])

        if flight_col:
            for _, row in raw.iterrows():
                add_flight(
                    row.get(flight_col),
                    destination=row.get(dest_col) if dest_col else "",
                    departure=row.get(dep_col) if dep_col else "",
                    boarding=row.get(board_col) if board_col else "",
                    gate=row.get(gate_col) if gate_col else "",
                    aircraft=row.get(aircraft_col) if aircraft_col else "",
                    reg=row.get(reg_col) if reg_col else "",
                    pax=row.get(pax_col) if pax_col else "",
                    trainee=row.get(trainee_col) if trainee_col else "לא",
                    training=row.get(training_col) if training_col else "",
                )

    # Case 3: raw grid fallback across all sheets
    if not flights:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        all_sheets = pd.read_excel(uploaded_file, sheet_name=None, header=None, dtype=object)
        for _, grid in all_sheets.items():
            for _, row in grid.iterrows():
                vals = list(row.values)
                for idx, val in enumerate(vals):
                    flight = _normalize_flight_cell(val)
                    if not flight:
                        continue

                    # Try to find time and destination near the flight cell.
                    # Hebrew exports are often RTL, so destination/time may be to the left.
                    near_vals = vals[max(0, idx - 10): min(len(vals), idx + 11)]
                    times = [_normalize_time_cell(v) for v in near_vals]
                    times = [t for t in times if t]
                    departure = times[0] if times else ""
                    boarding = times[1] if len(times) > 1 else ""

                    destination = _value_from_nearby_row(vals, idx, [-2, -1, 1, 2, -3, 3])
                    aircraft = _value_from_nearby_row(vals, idx, [-4, 4, -5, 5])
                    add_flight(flight, destination=destination, departure=departure, boarding=boarding, aircraft=aircraft)

    flights_df = pd.DataFrame(flights)

    wanted_cols = ["טיסה", "יעד", "המראה", "בורדינג", "גייט", "סוג מטוס", "רישוי", "נוסעים", "טרייני רצ", "סוג הכשרה"]
    if flights_df.empty:
        return pd.DataFrame(columns=wanted_cols)

    flights_df["_flight_key"] = flights_df["טיסה"].apply(flight_key)
    flights_df = flights_df.drop_duplicates(subset=["_flight_key"], keep="first").drop(columns=["_flight_key"])
    flights_df = flights_df[flights_df["המראה"].astype(str).str.strip() != ""].copy()
    flights_df = safe_sort_by_time(flights_df, "המראה")

    for col in wanted_cols:
        if col not in flights_df.columns:
            flights_df[col] = ""

    return flights_df[wanted_cols]


def normalize_employees(df):
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

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

    return df
