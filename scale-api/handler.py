"""scale-api: nhận lệnh preset từ nút Grafana, kiểm tra an toàn, rồi scale EC2 ASG / Lambda / MongoDB Atlas.

POST /scale   body: {"target": "asg" | "lambda" | "atlas", "preset": "standby" | "10k" | "30k" | "60k", "user": "<grafana login>"}
Header bắt buộc: X-Scale-Token (so với secret trong Secrets Manager).

Mọi preset đặt GIÁ TRỊ TUYỆT ĐỐI → bấm lặp lại không cộng dồn (idempotent).
"""
import base64
import datetime as dt
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

VN = dt.timezone(dt.timedelta(hours=7), "ICT")  # Việt Nam không có giờ mùa hè
asg = boto3.client("autoscaling")
lmb = boto3.client("lambda")
secrets = boto3.client("secretsmanager")

# ---------------------------------------------------------------------------
# Preset theo quy mô (BaoCaoSauThi.md §2, spec §6.2). Giá trị có dấu "# DUYỆT" cần SRE xác nhận lại.
# ---------------------------------------------------------------------------
PRESETS = {
    "standby": {
        "label": "Ngày thường",
        "asg": {"api": {"min": 2, "desired": 4, "max": 20},       # DUYỆT
                "oauth": {"min": 2, "desired": 2, "max": 10},     # DUYỆT
                "datawrk": {"min": 2, "desired": 2, "max": 10}},  # DUYỆT
        "lambda": {"examination-lambda": 200, "examination-lambda-oauth": 50},
        "atlas": {"cluster-exam": {"tier": "M10"}, "Cluster1": {"tier": "M20"}},
    },
    "10k": {
        "label": "< 10.000 thí sinh",
        "asg": {"api": {"min": 15, "desired": 15, "max": 30},     # DUYỆT
                "oauth": {"min": 8, "desired": 8, "max": 15},    # DUYỆT
                "datawrk": {"min": 2, "desired": 2, "max": 10}},
        "lambda": {"examination-lambda": 1000, "examination-lambda-oauth": 200},
        "atlas": {"cluster-exam": {"tier": "M40"}, "Cluster1": {"tier": "M40"}},
    },
    "30k": {
        "label": "< 30.000 thí sinh",
        "asg": {"api": {"min": 25, "desired": 25, "max": 50},     # DUYỆT
                "oauth": {"min": 15, "desired": 15, "max": 25},   # DUYỆT
                "datawrk": {"min": 2, "desired": 2, "max": 10}},
        "lambda": {"examination-lambda": 2000, "examination-lambda-oauth": 300},
        "atlas": {"cluster-exam": {"tier": "M50"}, "Cluster1": {"tier": "M50"}},
    },
    "60k": {
        "label": "~60.000 thí sinh",
        "asg": {"api": {"min": 40, "desired": 40, "max": 70},     # spec: api-elb 38–40, trần 70
                "oauth": {"min": 25, "desired": 25, "max": 30},   # spec: oauth 22–25
                "datawrk": {"min": 2, "desired": 2, "max": 10}},  # DUYỆT
        "lambda": {"examination-lambda": 3000, "examination-lambda-oauth": 500},
        "atlas": {"cluster-exam": {"tier": "M60", "disk_iops": 10000}, "Cluster1": {"tier": "M60"}},
    },
}

# Giới hạn cứng: không preset nào (kể cả sửa nhầm ở trên) được vượt
HARD_CAPS = {"lambda": {"examination-lambda": 3000, "examination-lambda-oauth": 500},
             "asg_max": 70, "atlas_tiers": ["M10", "M20", "M30", "M40", "M50", "M60"]}

ASG_NAMES = {  # nhãn → tên ASG thật (đọc từ CloudWatch account 097117637924)
    "api": os.environ.get("ASG_API", "api-demand-spot-auto-scaling-group"),
    "oauth": os.environ.get("ASG_OAUTH", "oauth-spot-medium-auto-scaling-group"),
    "datawrk": os.environ.get("ASG_DATAWRK", "datawrk-onluyen-vn"),
}
ATLAS_CLUSTERS = {  # tên logic → tên cluster trên Atlas
    "cluster-exam": os.environ.get("ATLAS_CLUSTER_EXAM", "cluster-exam"),
    "Cluster1": os.environ.get("ATLAS_CLUSTER_1", "Cluster1"),
}
TIER_ORDER = HARD_CAPS["atlas_tiers"]


class Rejected(Exception):
    """Lệnh bị chốt an toàn từ chối (HTTP 409)."""


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def _resp(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False)}


def _secret(arn_env):
    arn = os.environ.get(arn_env)
    if not arn:
        return None
    raw = secrets.get_secret_value(SecretId=arn)["SecretString"]
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _now_vn():
    return dt.datetime.now(VN)


def _in_exam_window(now=None):
    """EXAM_WINDOWS='15:00-21:45' (giờ VN, nhiều khoảng cách nhau bằng dấu phẩy). Trống = không có khung giờ thi."""
    now = now or _now_vn()
    for part in filter(None, (os.environ.get("EXAM_WINDOWS", "15:00-21:45")).split(",")):
        start, end = part.strip().split("-")
        s = dt.time.fromisoformat(start)
        e = dt.time.fromisoformat(end)
        if s <= now.time() <= e:
            return True, part.strip()
    return False, None


def _notify(text):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:  # thông báo lỗi không được làm hỏng lệnh chính
        log.warning("slack notify failed: %s", exc)


# ---------------------------------------------------------------------------
# Chốt an toàn: đọc trạng thái DB thi từ Prometheus (cùng nguồn với dashboard)
# ---------------------------------------------------------------------------
EXAM_SEL = 'cl_name=~"(?i).*exam.*"'
GATE_EXPR = ("clamp_max("
             f"(max(hardware_system_cpu_normalized_user_percent{{{EXAM_SEL}}} + hardware_system_cpu_normalized_kernel_percent{{{EXAM_SEL}}}) >= bool 75) + "
             f"(max(mongodb_connections_current{{{EXAM_SEL}}}) >= bool 25000) + "
             f"(100 * max(mongodb_wiredTiger_cache_tracked_dirty_bytes_in_the_cache{{{EXAM_SEL}}} / mongodb_wiredTiger_cache_maximum_bytes_configured{{{EXAM_SEL}}}) >= bool 20) + "
             f"(max(mongodb_globalLock_currentQueue_writers{{{EXAM_SEL}}}) > bool 10), 1)")


def _prom(expr):
    base = os.environ.get("PROM_URL")
    if not base:
        raise Rejected("Chưa cấu hình PROM_URL nên không kiểm tra được trạng thái DB — từ chối để an toàn.")
    url = base.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    req = urllib.request.Request(url)
    auth = _secret("PROM_AUTH_SECRET_ARN")  # tùy chọn: {"username": "...", "password": "..."}
    if isinstance(auth, dict) and auth.get("username"):
        token = base64.b64encode(f'{auth["username"]}:{auth["password"]}'.encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    try:
        data = json.load(urllib.request.urlopen(req, timeout=5))
    except Exception as exc:
        raise Rejected(f"Không đọc được Prometheus ({exc}) — từ chối để an toàn.")
    return data.get("data", {}).get("result", [])


def _scalar(expr):
    res = _prom(expr)
    if not res:
        raise Rejected(f"Prometheus không có dữ liệu cho chốt an toàn — từ chối để an toàn. ({expr[:80]}…)")
    return float(res[0]["value"][1])


def check_db_gate_for_scale_up():
    if os.environ.get("GATE_CHECK", "on") == "off":
        log.warning("GATE_CHECK=off — bỏ qua kiểm tra DB")
        return
    if _scalar(GATE_EXPR) >= 1:
        raise Rejected("Scaling Gate đang LOCK: DB thi đang căng (CPU ≥ 75% / kết nối ≥ 25K / dirty ≥ 20% / hàng đợi ghi > 10). "
                       "Thêm máy hoặc tăng Lambda lúc này chỉ đổ thêm tải vào DB.")


# ---------------------------------------------------------------------------
# EC2 Auto Scaling
# ---------------------------------------------------------------------------
def apply_asg(preset, dry_run):
    cfg = PRESETS[preset]["asg"]
    names = [ASG_NAMES[k] for k in cfg]
    current = {g["AutoScalingGroupName"]: g for g in asg.describe_auto_scaling_groups(AutoScalingGroupNames=names)["AutoScalingGroups"]}
    plan, scaling_up = [], False
    for key, want in cfg.items():
        name = ASG_NAMES[key]
        g = current.get(name)
        if not g:
            raise Rejected(f"Không tìm thấy ASG {name}")
        if not (want["min"] <= want["desired"] <= want["max"] <= HARD_CAPS["asg_max"]):
            raise Rejected(f"{name}: preset sai (cần Min ≤ Desired ≤ Max ≤ {HARD_CAPS['asg_max']})")
        scaling_up |= want["desired"] > g["DesiredCapacity"] or want["max"] > g["MaxSize"]
        plan.append({"asg": name,
                     "min": f'{g["MinSize"]} → {want["min"]}',
                     "desired": f'{g["DesiredCapacity"]} → {want["desired"]}',
                     "max": f'{g["MaxSize"]} → {want["max"]}',
                     "_set": (name, want["min"], want["desired"], want["max"])})
    if scaling_up:
        check_db_gate_for_scale_up()
    if not scaling_up and _in_exam_window()[0]:
        raise Rejected("Đang trong khung giờ thi — không hạ số máy. Hạ tải sau 21:45.")
    if not dry_run:
        # Min = Desired nghĩa là "khóa scale-in" (spec: Suspend ScaleIn) mà ASG vẫn tự thay máy lỗi.
        for name, mn, desired, mx in (i["_set"] for i in plan):
            asg.update_auto_scaling_group(AutoScalingGroupName=name, MinSize=mn, MaxSize=mx, DesiredCapacity=desired)
    return [{k: v for k, v in i.items() if not k.startswith("_")} for i in plan]


# ---------------------------------------------------------------------------
# Lambda Reserved Concurrency
# ---------------------------------------------------------------------------
def apply_lambda(preset, dry_run):
    cfg = PRESETS[preset]["lambda"]
    plan, scaling_up = [], False
    for fn, want in cfg.items():
        cap = HARD_CAPS["lambda"].get(fn)
        if cap is not None and want > cap:
            raise Rejected(f"{fn}: Reserved {want} vượt trần cứng {cap} (giới hạn socket DB M60)")
        cur = lmb.get_function_concurrency(FunctionName=fn).get("ReservedConcurrentExecutions")
        scaling_up |= cur is None or want > cur
        plan.append({"function": fn, "reserved": f"{cur if cur is not None else 'không đặt'} → {want}"})
    if scaling_up:
        check_db_gate_for_scale_up()
    if not dry_run:
        for fn, want in cfg.items():
            lmb.put_function_concurrency(FunctionName=fn, ReservedConcurrentExecutions=want)
    return plan


# ---------------------------------------------------------------------------
# MongoDB Atlas (Admin API v2, digest auth)
# ---------------------------------------------------------------------------
ATLAS_BASE = "https://cloud.mongodb.com/api/atlas/v2"
ATLAS_ACCEPT = "application/vnd.atlas.2023-02-01+json"


def _atlas(method, path, body=None):
    key = _secret("ATLAS_SECRET_ARN")  # {"public_key": "...", "private_key": "...", "group_id": "..."}
    if not isinstance(key, dict):
        raise Rejected("Chưa cấu hình ATLAS_SECRET_ARN")
    pwd = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pwd.add_password(None, ATLAS_BASE, key["public_key"], key["private_key"])
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pwd))
    url = f'{ATLAS_BASE}/groups/{key["group_id"]}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": ATLAS_ACCEPT, "Content-Type": ATLAS_ACCEPT})
    try:
        return json.load(opener.open(req, timeout=20))
    except urllib.error.HTTPError as exc:
        raise Rejected(f"Atlas API lỗi {exc.code}: {exc.read().decode()[:300]}")


def _atlas_specs(cluster):
    """Trả về list (spec_dict) của mọi electable/readOnly/analytics specs để đổi instanceSize."""
    out = []
    for rs in cluster.get("replicationSpecs", []):
        for rc in rs.get("regionConfigs", []):
            for k in ("electableSpecs", "readOnlySpecs", "analyticsSpecs"):
                if rc.get(k) and rc[k].get("nodeCount", 0) > 0:
                    out.append(rc[k])
    return out


def check_atlas_safe(name, cluster, scaling_down):
    in_win, win = _in_exam_window()
    if in_win:
        raise Rejected(f"Đang trong khung giờ thi ({win}) — CẤM đổi tier MongoDB (sự cố 29/10: mất Primary 24 giây). "
                       "Tăng tier phải xong trước T-4h; hạ sau 21:45.")
    if cluster.get("stateName") != "IDLE":
        raise Rejected(f"{name} đang ở trạng thái {cluster.get('stateName')} (rolling update chưa xong) — đợi IDLE.")
    if scaling_down and os.environ.get("GATE_CHECK", "on") != "off":
        sel = f'cl_name="{name}"'
        dirty = _scalar(f"100 * max(mongodb_wiredTiger_cache_tracked_dirty_bytes_in_the_cache{{{sel}}} / "
                        f"mongodb_wiredTiger_cache_maximum_bytes_configured{{{sel}}})")
        if dirty >= 15:
            raise Rejected(f"{name}: dirty cache {dirty:.1f}% ≥ 15% — chưa an toàn để hạ tier.")


def apply_atlas(preset, dry_run):
    cfg = PRESETS[preset]["atlas"]
    plan, todo = [], []
    for logical, want in cfg.items():
        name = ATLAS_CLUSTERS[logical]
        if want["tier"] not in TIER_ORDER:
            raise Rejected(f"Tier {want['tier']} không nằm trong danh sách cho phép {TIER_ORDER}")
        cluster = _atlas("GET", f"/clusters/{urllib.parse.quote(name)}")
        specs = _atlas_specs(cluster)
        cur = specs[0]["instanceSize"] if specs else "?"
        if cur == want["tier"] and ("disk_iops" not in want or specs[0].get("diskIOPS") == want["disk_iops"]):
            plan.append({"cluster": name, "tier": f"{cur} (giữ nguyên)"})
            continue
        down = cur in TIER_ORDER and TIER_ORDER.index(want["tier"]) < TIER_ORDER.index(cur)
        check_atlas_safe(name, cluster, down)
        for sp in specs:
            sp["instanceSize"] = want["tier"]
            if "disk_iops" in want:
                sp["diskIOPS"] = want["disk_iops"]
        plan.append({"cluster": name, "tier": f"{cur} → {want['tier']}",
                     **({"diskIOPS": want["disk_iops"]} if "disk_iops" in want else {})})
        todo.append((name, cluster["replicationSpecs"]))
    if not dry_run:
        for name, rspecs in todo:
            _atlas("PATCH", f"/clusters/{urllib.parse.quote(name)}", {"replicationSpecs": rspecs})
    return plan


TARGETS = {"asg": apply_asg, "lambda": apply_lambda, "atlas": apply_atlas}


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = _secret("TOKEN_SECRET_ARN")
    token = token.get("token") if isinstance(token, dict) else token
    if not token or not hmac.compare_digest(headers.get("x-scale-token", ""), str(token)):
        return _resp(401, {"ok": False, "error": "Sai hoặc thiếu X-Scale-Token"})

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        req = json.loads(raw)
    except ValueError:
        return _resp(400, {"ok": False, "error": "Body không phải JSON"})

    target, preset = req.get("target"), req.get("preset")
    user = str(req.get("user") or "không rõ")[:100]
    dry_run = bool(req.get("dry_run", False))
    if target not in TARGETS or preset not in PRESETS:
        return _resp(400, {"ok": False, "error": f"target phải thuộc {list(TARGETS)}, preset thuộc {list(PRESETS)}"})

    label = PRESETS[preset]["label"]
    audit = {"user": user, "target": target, "preset": preset, "dry_run": dry_run,
             "request_id": getattr(context, "aws_request_id", None), "time_vn": _now_vn().isoformat()}
    try:
        plan = TARGETS[target](preset, dry_run)
    except Rejected as exc:
        log.info(json.dumps({**audit, "result": "REJECTED", "reason": str(exc)}, ensure_ascii=False))
        _notify(f":no_entry: {user} bấm *{target} → {label}* — BỊ CHẶN: {exc}")
        return _resp(409, {"ok": False, "rejected": True, "reason": str(exc)})
    except Exception as exc:  # lỗi AWS/Atlas
        log.exception("scale failed")
        _notify(f":x: {user} bấm *{target} → {label}* — LỖI: {exc}")
        return _resp(500, {"ok": False, "error": str(exc)})

    log.info(json.dumps({**audit, "result": "DRY_RUN" if dry_run else "APPLIED", "plan": plan}, ensure_ascii=False))
    _notify(f":white_check_mark: {user} {'xem trước' if dry_run else 'đã áp dụng'} *{target} → {label}*\n"
            + "\n".join("• " + ", ".join(f"{k}: {v}" for k, v in p.items()) for p in plan))
    return _resp(200, {"ok": True, "dry_run": dry_run, "preset": label, "plan": plan})
