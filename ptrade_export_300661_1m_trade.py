from datetime import datetime


SECURITY = "300661.SZ"
FREQUENCY = "1m"
FQ = "pre"
FIELDS = ["open", "high", "low", "close", "volume", "money", "price"]
START_DATE = "2005-01-01 09:30"
CHUNK_MONTHS = 1
RECENT_COUNT_CANDIDATES = [200000, 100000, 50000, 20000, 10000, 5000, 1000]

EXPORT_DONE = False
EXPORT_ATTEMPTED = False


def _log(message):
    try:
        log.info(message)
    except Exception:
        print(message)


def _base_dir():
    try:
        return get_research_path()
    except Exception:
        return "."


def _output_path():
    base_dir = _base_dir()
    if base_dir.endswith("\\") or base_dir.endswith("/"):
        return base_dir + "300661_SZ_1m_ptrade.csv"
    return base_dir + "/300661_SZ_1m_ptrade.csv"


def _month_start(dt_obj):
    return datetime(dt_obj.year, dt_obj.month, 1, 9, 30)


def _next_month(dt_obj):
    if dt_obj.month == 12:
        return datetime(dt_obj.year + 1, 1, 1, 9, 30)
    return datetime(dt_obj.year, dt_obj.month + 1, 1, 9, 30)


def _iter_month_ranges(start_dt, end_dt):
    ranges = []
    current = start_dt
    while current <= end_dt:
        next_anchor = _next_month(_month_start(current))
        current_end = next_anchor.replace(hour=15, minute=0) 
        if current_end > end_dt:
            current_end = end_dt
        ranges.append((current, current_end))
        if next_anchor > end_dt:
            break
        current = next_anchor
    return ranges


def _pick_frame(data):
    if isinstance(data, dict):
        if SECURITY in data:
            return data[SECURITY]
        if len(data) == 1:
            return list(data.values())[0]
    return data


def _to_records(data):
    frame = _pick_frame(data)
    if frame is None:
        return []

    try:
        if hasattr(frame, "empty") and frame.empty:
            return []
    except Exception:
        pass

    temp = frame
    try:
        if hasattr(frame, "reset_index"):
            temp = frame.reset_index()
    except Exception:
        temp = frame

    if hasattr(temp, "to_dict"):
        try:
            records = temp.to_dict("records")
        except Exception:
            records = []
    elif isinstance(temp, list):
        records = temp
    else:
        records = []

    normalized = []
    for row in records:
        if not isinstance(row, dict):
            continue

        dt_value = (
            row.get("datetime")
            or row.get("day")
            or row.get("date")
            or row.get("dt")
            or row.get("index")
        )
        if dt_value is None:
            continue

        normalized.append(
            {
                "datetime": str(dt_value),
                "code": str(row.get("code") or SECURITY),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("amount", row.get("money")),
                "price": row.get("price", row.get("close")),
            }
        )

    normalized.sort(key=lambda x: (x["datetime"], x["code"]))

    deduped = []
    seen = set()
    for row in normalized:
        key = (row["datetime"], row["code"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _write_csv(records, output_path):
    fieldnames = ["datetime", "code", "open", "high", "low", "close", "volume", "amount", "price"]
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(",".join(fieldnames) + "\n")
        for row in records:
            values = []
            for key in fieldnames:
                value = row.get(key)
                if value is None:
                    text = ""
                else:
                    text = str(value)
                text = text.replace("\r", " ").replace("\n", " ").replace(",", " ")
                values.append(text)
            f.write(",".join(values) + "\n")


def _export_via_get_price():
    if "get_price" not in globals():
        raise RuntimeError("get_price is not available in current PTrade runtime")

    start_dt = datetime.strptime(START_DATE, "%Y-%m-%d %H:%M")
    now_dt = datetime.now()
    end_dt = datetime(now_dt.year, now_dt.month, now_dt.day, 15, 0)

    _log(
        "[get_price] start export security=%s frequency=%s fq=%s range=%s -> %s"
        % (
            SECURITY,
            FREQUENCY,
            FQ,
            start_dt.strftime("%Y-%m-%d %H:%M"),
            end_dt.strftime("%Y-%m-%d %H:%M"),
        )
    )

    all_records = []
    for chunk_start, chunk_end in _iter_month_ranges(start_dt, end_dt):
        _log(
            "[get_price] request chunk %s -> %s"
            % (
                chunk_start.strftime("%Y-%m-%d %H:%M"),
                chunk_end.strftime("%Y-%m-%d %H:%M"),
            )
        )
        chunk = get_price(
            security=SECURITY,
            start_date=chunk_start.strftime("%Y-%m-%d %H:%M"),
            end_date=chunk_end.strftime("%Y-%m-%d %H:%M"),
            frequency=FREQUENCY,
            fields=FIELDS,
            fq=FQ,
        )
        records = _to_records(chunk)
        _log("[get_price] chunk rows=%s" % len(records))
        if records:
            all_records.extend(records)

    if not all_records:
        raise RuntimeError("get_price returned no data")

    all_records.sort(key=lambda x: (x["datetime"], x["code"]))
    deduped = []
    seen = set()
    for row in all_records:
        key = (row["datetime"], row["code"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _export_via_get_history():
    if "get_history" not in globals():
        raise RuntimeError("get_history is not available in current PTrade runtime")

    last_error = None
    for count in RECENT_COUNT_CANDIDATES:
        try:
            _log("[get_history] trying count=%s" % count)
            try:
                data = get_history(
                    count,
                    frequency=FREQUENCY,
                    field=FIELDS,
                    security_list=[SECURITY],
                    fq=FQ,
                    is_dict=True,
                )
            except TypeError:
                data = get_history(
                    count,
                    frequency=FREQUENCY,
                    field=FIELDS,
                    security_list=[SECURITY],
                )
            records = _to_records(data)
            if records:
                return records
        except Exception as exc:
            last_error = exc
            _log("[get_history] count=%s failed: %s" % (count, exc))

    raise RuntimeError("get_history fallback failed: %s" % last_error)


def export_300661_1m():
    output_path = _output_path()
    try:
        records = _export_via_get_price()
        source = "get_price"
    except Exception as exc:
        _log("[get_price] failed: %s" % exc)
        _log("[fallback] switching to get_history")
        records = _export_via_get_history()
        source = "get_history"

    _write_csv(records, output_path)
    _log(
        "[export_done] source=%s rows=%s start=%s end=%s output=%s"
        % (
            source,
            len(records),
            records[0]["datetime"] if records else None,
            records[-1]["datetime"] if records else None,
            output_path,
        )
    )
    return records


def initialize(context):
    global EXPORT_DONE
    set_universe([SECURITY])
    _log("[initialize] security=%s" % SECURITY)
    _log("[initialize] export will be triggered on first handle_data minute")


def before_trading_start(context, data):
    return


def handle_data(context, data):
    global EXPORT_DONE
    global EXPORT_ATTEMPTED

    if EXPORT_DONE or EXPORT_ATTEMPTED:
        return

    EXPORT_ATTEMPTED = True

    try:
        now_dt = context.blotter.current_dt
        _log("[handle_data] trigger export at %s" % now_dt)
    except Exception:
        _log("[handle_data] trigger export")

    try:
        export_300661_1m()
        EXPORT_DONE = True
        _log("[handle_data] export finished")
    except Exception as exc:
        _log("[handle_data_export_error] %s" % exc)


def after_trading_end(context, data):
    return
