# Review — Module 3: Bảng Điều Khiển `/control` & AWS EventBridge Control Plane

| | |
| :--- | :--- |
| **Plan được review** | `docs/plans/2026-11-15-gitnexus-plan-module-three-eventbridge-control.md` |
| **Repo** | `gitlab.edmicro.io/devsecops/live-exam-noc` — nhánh `master`, commit `6518515` |
| **Ngày review** | 2026-11-26 |
| **Tài liệu đối chiếu** | `docs/specs/2026-11-12-spec-monitoring-overview-dashboard.md` (§6–§9) · `docs/plans/2026-11-15-gitnexus-plan-cross-module-architecture-specs.md` · plan Module 1, 2, 4 · `data-2-5.11.2026/BaoCaoSauThi.md`, `plan-exam.md` · `demo/monitor-demo.html` (Tab 3) |

## Trạng thái xử lý (cập nhật 2026-11-26)

Toàn bộ vấn đề đã được xử lý trong **[plan v2](2026-11-26-plan-module-three-eventbridge-control-v2.md)** và **[bản vá demo](demo-patch/monitor-demo.patch)**. Sáu câu hỏi ở §7 được chốt theo phương án đề xuất (plan v2 §11) và **cần Tech Lead/SA xác nhận**.

| Mục | Xử lý tại |
| :--- | :--- |
| B1 Ranh giới repo | v2 §2 (D1–D4), §10 |
| B2 RBAC L1 | v2 §6.2; demo: khóa mọi nút hạ tầng với L1, sửa dòng audit mẫu |
| B3 Webhook khóa nhầm | v2 §6.1: poll 15s là nguồn chính, webhook chỉ kích hoạt poll, TTL 90s |
| B4 Fail-closed | v2 §6.1 trạng thái `UNKNOWN`, §6.3 các lệnh cứu hộ |
| B5 Scheduler và TOCTOU | v2 §6.5 (lệnh trạng thái đích, 12 lịch hạ tải), §6.6 bước 5 (executor kiểm tra lại) |
| M1 PutEvents v2 | v2 §5.1 |
| M2 Idempotency | v2 §5.4, §6.6 bước 3–4 |
| M3 Rule và detail-type | v2 §5.2; demo: `Source`, `DetailType`, tên trường snake_case |
| M4 Preset | v2 §6.4 (tách lệnh con, tất cả qua hoặc không gửi) |
| M5 Interlock | v2 §6.3 (bảng đầy đủ, giới hạn cứng) |
| M6 Audit append-only | v2 §5.4, §6.9 |
| M7 Xác thực webhook | v2 §6.1 (webhook chỉ kích hoạt, không cần HMAC) |
| M8 Ngưỡng định nghĩa 2 nơi | v2 §6.1 (chỉ đọc trạng thái alert rule) |
| Minor 1–2 | v2 §8, §10 |
| Minor 3–5 | v2 §6.8; demo: Dry-Run mặc định bật, `closedby="closerequest"` |
| Minor 6 | v2 §6.5 (mốc 20:50, lịch theo ca thi) |
| Minor 7–8 | v2 §6.2 (Cognito), §6.8 (không iframe, `frame-ancestors 'none'`) |
| Minor 9 | v2 §6.6 (rule DLQ của Grafana và banner) |
| Minor 10 | v2 §9 (rate limit Atlas) |
| §5 Trích dẫn | v2 dùng đường dẫn và số dòng tại commit `6518515` |

## 0. Kết luận

**Chưa nên triển khai theo plan này.** Hướng kiến trúc tổng thể vẫn đúng: Grafana chỉ đọc, `/control` mỏng, mọi lệnh đi qua EventBridge, có Dry-Run, 2 bước xác nhận và Audit Log. Tuy nhiên plan đang lệch với các tài liệu khác ở ba điểm nền tảng:

1. **Phạm vi và nơi chứa code mâu thuẫn với plan cross-module**, tài liệu chốt ranh giới giữa 4 team và ra đời cùng ngày.
2. **Phân quyền RBAC của `EXAM_DUTY_OPERATOR` trái với spec.** Plan cho người trực thi (non-tech) bấm các lệnh thay đổi hạ tầng.
3. **Cơ chế đồng bộ Gate có lỗi thiết kế.** Theo đúng plan, `/control` sẽ tự rơi vào trạng thái `LOCK` gần như suốt thời gian không có alert.

Cần sửa plan theo §1 và §2 bên dưới trước khi bắt đầu Bước 1.

---

## 1. Vấn đề chặn triển khai (Blocker)

### B1. Phạm vi và vị trí code mâu thuẫn với plan cross-module

| Hạng mục | Plan Module 3 | Plan cross-module (§1, §3.3 RACI #7, #8, #10) |
| :--- | :--- | :--- |
| Nơi chứa code | `control/`, `control/executors/` nằm ngay trong repo `DevOpsThiSo` | Repo `DevOpsThiSo` **chỉ chứa specs**, "tuyệt đối không viết code runtime của Executor" |
| Executor | 3 Lambda trong `control/executors/` | **External Executor Service** đặt ở repo riêng, do **Team AWS Lambda** sở hữu |
| EventBridge Scheduler | `control/scheduler_presets.py` | Terraform do **Team DevSecOps** sở hữu. Plan Module 4 cũng định nghĩa Scheduler trong `eventbridge_control.tf`, nên đang trùng việc |
| Cập nhật trạng thái Audit | Executor ghi thẳng `SUCCESS/FAILED` vào Audit Log | Executor bắn sự kiện `edmicro.executor.status` lên bus, Control Panel nhận và cập nhật |

**Đề xuất:** Viết lại §6 và §10 theo 3 deliverable riêng:

- **Control Panel** (UI + API): Team Lambda làm backend, DevSecOps lo hosting, SSO và Audit DB.
- **External Executor Service**: repo riêng.
- **Bản yêu cầu tài nguyên** (`runtime, memory, timeout, env_vars, required_iam_actions`) giao cho DevSecOps đưa vào Terraform.

Xóa `scheduler_presets.py` khỏi Module 3. Module 3 chỉ cần quy định **payload** mà Scheduler sẽ gửi.

### B2. RBAC của `EXAM_DUTY_OPERATOR` trái với spec

- **Plan §6.2:** Duty Operator được bấm ACK, **`circuit_breaker`, `waiting_room` và `preset`**.
- **Spec §7.1 (dòng 332–334):** Duty Operator chỉ được ACK, Mute/Unmute, gửi yêu cầu "Báo DevOps kích hoạt SOP", copy thông báo. **Toàn bộ nút thay đổi hạ tầng bị khóa hoặc ẩn.**
- **Cross-module §3.4 #5:** "Ẩn/khóa 100% nút hạ tầng" đối với L1.
- **Test trong plan §8.3** lặp lại sai lệch này ("bấm `circuit_breaker` → cho phép").
- **`preset`** gồm cả scale tier DB, Reserved/Provisioned Lambda và ASG. Như vậy Duty Operator có thể gián tiếp kích hoạt mọi thay đổi lớn.
- **Demo** (`monitor-demo.html:1577`) có một dòng audit mẫu là `EXAM_DUTY_OPERATOR` bật Provisioned Pha 1. Cần sửa demo để tránh dev bắt chước.

**Đề xuất:**
- L1 chỉ có `ack`, `mute`, `copy_notice` và `request_sop(S1..S5)`. Lệnh `request_sop` gửi Pager/Slack cho L2 kèm link Dry-Run và **không gọi `PutEvents` lên bus điều khiển**.
- Sửa test thành: L1 gọi bất kỳ lệnh hạ tầng nào, kể cả `circuit_breaker` và `preset`, đều nhận `403`.

### B3. Đồng bộ Gate: dùng webhook làm "nhịp tim" sẽ khóa nhầm liên tục

- **Plan §6.1:** nếu `stale > 60s` thì đặt `ScalingGate = LOCK`. **Plan §3:** nếu webhook trễ quá 30s thì chuyển sang hỏi Grafana.
- **Thực tế:** Grafana Alerting **chỉ gửi webhook khi trạng thái nhóm alert thay đổi**, hoặc theo `repeat_interval` (mặc định 4 giờ, plan cross-module đặt cooldown 3–5 phút). Khi hệ thống bình thường và không có alert nào, sẽ **không có webhook nào được gửi**. Nếu đo độ "stale" theo thời điểm nhận webhook cuối cùng, gate sẽ chuyển `LOCK` sau 60s và ở yên đó.
- **Ngưỡng thời gian không thống nhất:** plan có 30s và 60s, cross-module chốt `gate_ttl_sec = 90s` (`LOCKED_UNKNOWN`) và `max_staleness = 120s`.

**Đề xuất:**
1. Xác định độ "tươi" của gate theo **lần đọc trạng thái thành công gần nhất**, không theo webhook. Control API poll định kỳ 15–20s trạng thái alert của Grafana (`GET /api/alertmanager/grafana/api/v2/alerts` hoặc `GET /api/prometheus/grafana/api/v1/rules`). Webhook chỉ dùng để **cập nhật nhanh hơn** giữa hai lần poll.
2. Nếu muốn giữ webhook làm tín hiệu sống, thêm một alert **Watchdog luôn ở trạng thái firing** với `repeat_interval` ngắn, định tuyến riêng tới `GateSyncWebhook`.
3. Thống nhất **một** bộ ngưỡng theo cross-module (`gate_ttl_sec = 90s`) và ghi rõ trong spec `grafana-gate-sync-contract.md`.

### B4. Fail-closed đang quá hẹp, và đang chặn cả lệnh cứu hộ

- **Plan:** mất Grafana thì đặt `ScalingGate = LOCK`. Không nói gì về `SafetyScaleDownGate` hay cửa sổ khóa tier DB.
- **Cross-module §3.4 #5:** trạng thái `LOCKED_UNKNOWN` khóa **Scale Out ASG, Scale Tier và Scale Down**, nhưng **vẫn cho phép** các lệnh cứu hộ giảm tải (`mute_event_monitor = 0`, `kill_slow_queries`, `alb 503`, `Waiting Room`) với xác nhận 2 bước.

**Đề xuất:** Gate có 4 trạng thái `GREEN / YELLOW / RED / UNKNOWN`. Viết bảng quyết định cho từng `detail-type` × trạng thái gate × vai trò × cửa sổ thời gian (xem §4).

### B5. Interlock chỉ chặn ở `/control`; lệnh từ Scheduler và độ trễ thực thi vượt qua được

- Interlock trong plan chỉ chạy ở `control/rbac_interlock.py`. **Lệnh từ EventBridge Scheduler đi thẳng lên bus** mà không qua `/control`. Ví dụ lịch 21:45 "Resume ScaleIn, hạ 50 → 35 → 25" và "hạ tier về Standby" sẽ chạy mà không kiểm tra Safety Gate 5/5, dù spec §6.2 bắt buộc phải kiểm tra.
- **Lỗi TOCTOU (kiểm tra xong nhưng điều kiện đổi trước khi chạy):** gate được kiểm tra lúc bấm, còn executor chạy bất đồng bộ, có thể sau vài lần retry. Đến lúc đó DB có thể đã chuyển Đỏ.

**Đề xuất:**
- **Executor phải kiểm tra lại các chốt an toàn cứng** ngay trước khi gọi API: trần Reserved ≤ 3.000, khóa tier/IOPS trong giờ thi, không scale out khi gate `RED/UNKNOWN`, Safety Gate trước khi scale down.
- Từ chối các event đã quá `expires_at_utc`.
- Event mang theo `safety_gate_snapshot` để ghi audit. Giá trị này **không thay thế** việc kiểm tra lại.
- Với lịch scale-down, Scheduler chỉ gửi **yêu cầu**. Executor kiểm tra Safety Gate và trả `SKIPPED_GATE_NOT_MET` nếu chưa đạt. Cần có cơ chế thử lại sau mỗi 5 phút.

---

## 2. Vấn đề lớn (Major)

### M1. Hợp đồng `PutEvents` đang dùng phiên bản cũ (v1)

Plan chỉ có `action_id`. Cross-module đã chốt bản v2 gồm `schema_version: "2.0"`, `idempotency_key`, `idempotency_ttl_sec`, `expires_at_utc`, `safety_gate_snapshot`, và key cố định cho Scheduler `sched:<rule>:<window_utc>:<target>`.

Plan Module 3 là bên **producer**, nên phải sinh đúng các trường này.

### M2. Chống chạy trùng (idempotency) mới ở mức "kiểm tra `action_id`"

Cần làm đủ theo cross-module:

- DynamoDB conditional write (`attribute_not_exists`) cùng lease TTL 60s.
- Mutex theo từng target, tránh xung đột giữa Scheduler và người bấm tay, ví dụ 19:15 Scheduler bật Provisioned đúng lúc L2 bấm tay.
- Máy trạng thái: `UNSEEN → IN_PROGRESS → SUCCEEDED / SKIPPED_DUPLICATE / EXPIRED_STALE / AMBIGUOUS_MANUAL_CHECK`.
- **Lệnh không idempotent** (`rs.stepDown`, `killOp`): nếu worker crash khi lease hết hạn thì **không tự chạy lại**, chuyển sang `AMBIGUOUS_MANUAL_CHECK` và báo L2.

Plan hiện chỉ test idempotency cho `db_executor`. Cần test cho cả 3 miền.

### M3. Nhầm giữa tên Rule và `detail-type`

- **Plan §3:** "`DetailType` khớp 4 Rules (`ops.preset.apply`, `ops.db.control`, …)".
- **Spec §6.2:** `detail-type` là động từ cụ thể (`atlas.tier.scale`, `lambda.circuit_breaker.mute_event_monitor`, `asg.capacity.update`, …). `ops.*.control` là **tên Rule**, mỗi Rule khớp theo **tiền tố** `detail-type`.
- **Demo** (`monitor-demo.html:2003–2006`) đang gửi `DetailType: 'ops.lambda.control'`, `Source: 'monitor.edmicro.io'` (spec ghi `edmicro.monitor.control`), và tên trường viết camelCase (`actorRole`, `dryRun`) trong khi spec dùng `role`, `dry_run`.

**Đề xuất:** Thêm bảng ánh xạ `detail-type → Rule → Executor → IAM role`, và đặt EventBridge event pattern theo `prefix`.

### M4. Rule `ops.preset.apply` không có executor xử lý

Plan có 4 Rule nhưng chỉ 3 executor. Cần chọn một trong hai cách cho Preset:

- **(a)** `/control` tách preset thành N lệnh nhỏ trong miền db, lambda, asg, mỗi lệnh có `idempotency_key` riêng và cùng `parent_action_id`.
- **(b)** Thêm một orchestrator, ví dụ Step Functions. Demo có nhắc "Step Functions / Automation Lambda" ở `monitor-demo.html:1031`.

Khuyến nghị **(a)**: đơn giản hơn, mỗi miền được interlock riêng, và Dry-Run hiển thị đủ N thay đổi.

### M5. Interlock thiếu và lệch so với spec §6.2 và §7.3

| Interlock theo spec | Plan | Ghi chú |
| :--- | :--- | :--- |
| Khóa `atlas.tier.scale` **và `atlas.iops.update`** trong giờ thi | Chỉ có `atlas.tier.scale` | Thiếu IOPS |
| Chặn **tăng EC2 và Lambda** khi `cluster-exam` Đỏ | Chỉ chặn `asg.capacity.update` | Thiếu `lambda.concurrency.set_reserved/set_provisioned` khi **tăng** |
| Mức chặn tăng: **Đỏ** | Vàng hoặc Đỏ | Plan chặt hơn spec. Cần chốt; nếu chặn ở Vàng, S5 có thể không scale kịp |
| Trần `examination-lambda` Reserved ≤ 3.000 | Chỉ nhắc trong executor | Phải là interlock cứng ở **cả** `/control` lẫn executor (cross-module #3) |
| Safety Gate scale-down: `IDLE`, CPU < ngưỡng, Dirty < 15%, Cooldown ≥ 15p (spec); thêm `SQS == 0` (demo) | Ghi "5/5" nhưng chỉ liệt kê 4 điều kiện, không có CPU | Cần định nghĩa đúng 5 điều kiện và ngưỡng CPU (demo dùng `dbCpu < 25`) |
| "Cửa sổ giờ thi" | Không định nghĩa | Cần cấu hình theo ngày thi, ví dụ `T-4h .. 21:45 VN`, thay vì để cứng trong code |

### M6. Audit Log "bất biến" nhưng plan lại cập nhật trạng thái tại chỗ

Spec §9.1 yêu cầu **Audit Log bất biến**, giữ 180 ngày. Plan ghi `PENDING` rồi cập nhật `SUCCESS/FAILED`, tức là ghi đè.

**Đề xuất:** Lưu theo kiểu chỉ thêm (append-only): mỗi lần đổi trạng thái là một bản ghi mới, khóa `action_id + sequence_no` (cross-module có `state_rank/sequence_no` chống nhận sai thứ tự). Trạng thái hiện tại tính từ bản ghi có `state_rank` cao nhất. Bật DynamoDB PITR và giới hạn IAM chỉ cho `PutItem` (không `UpdateItem/DeleteItem`) với role của app.

### M7. Xác thực webhook

Plan dùng Bearer token, cross-module chốt **HMAC-SHA256**.

- Cần xác nhận phiên bản Grafana đang dùng có hỗ trợ ký HMAC cho contact point webhook hay không. Nếu không, đặt một bridge (Team Lambda) ở giữa để ký lại.
- Bổ sung chống replay: header timestamp và sai lệch tối đa 5 phút.
- Payload webhook của Grafana là **danh sách alert theo nhóm**, không phải một trạng thái gate. Cần quy định rõ hàm quy đổi `alerts[] → GateState`, ví dụ S1 hoặc S2 firing thì `RED`, và quy tắc nhận `resolved`.

### M8. Kiểm tra lại gate bằng `/api/ds/query` làm ngưỡng bị định nghĩa hai nơi

Plan tự truy vấn `exam:wiredtiger_dirty_cache_pct`, `CONNECTIONS`, `Write IOPS` rồi tự đánh giá ngưỡng. Như vậy ngưỡng S1–S5 có hai nguồn (Grafana alert rule và code `/control`), dễ lệch nhau theo thời gian.

**Đề xuất:** Lấy **trạng thái alert** (`/api/prometheus/grafana/api/v1/rules` hoặc alertmanager) làm nguồn duy nhất. Chỉ dùng `/api/ds/query` để **hiển thị** số liệu trong Dry-Run Diff.

---

## 3. Vấn đề nhỏ và nhất quán tài liệu (Minor)

1. **Tên file test** không thống nhất: §8 ghi `tests/test_control_*.py`, còn §10, §11 và §13 ghi `tests/test_control_plane.py`.
2. **`files_to_modify: []`** trong YAML trong khi §10 liệt kê 9 file. `primary_symbols` và `related_symbols` cũng để trống.
3. **Dry-Run phải bật mặc định** (spec §7.3), nhưng demo để checkbox `chk-dry-run` **không được chọn** (`monitor-demo.html:1040`). Khi chuyển sang app thật: mặc định là Dry-Run; muốn chạy thật thì phải chạy Dry-Run trước và có `dry_run_ref` hợp lệ trong N phút.
4. **Vai trò phía client:** demo đổi role bằng `<select>` trên client (`monitor-demo.html:1035`). Khi chuyển sang app thật, role **chỉ** lấy từ claim JWT/OIDC ở server. Plan nên ghi rõ điều này trong mục "avoid".
5. **`<dialog closedby="any">`:** bấm ra ngoài sẽ đóng dialog, có thể chấp nhận vì kết quả là hủy. Với thao tác `CRITICAL`, nên dùng `closedby="closerequest"` và yêu cầu gõ lại tên target, ví dụ `cluster-exam`.
6. **Lịch Scheduler:** plan liệt kê `T-4h, T-45p, P1, P2, T-10p, 21:45` nhưng thiếu mốc **sau 20:50 trả Provisioned = 0** (spec §6.2). Ngoài ra `T-4h (15:00)` và các giờ khác đang **cố định theo một ca 19:00**; cần tham số hóa theo lịch ca thi.
7. **Ranh giới SSO:** plan ghi "Cognito/SSO groups", Module 4 ghi "Cognito hoặc Google Workspace OIDC". Cần chốt IdP và claim chứa group, ví dụ `cognito:groups`.
8. **Iframe hay link:** Module 2 còn để mở câu hỏi nhúng iframe (`GF_SECURITY_ALLOW_EMBEDDING`, CSP `frame-ancestors`). Nếu nhúng iframe, `/control` phải chống clickjacking cho các nút thực thi; nên chỉ dùng link mở tab mới.
9. **Banner DLQ đỏ** (§9): `/control` cần quyền đọc `ApproximateNumberOfMessagesVisible` của DLQ, hoặc nhận alert từ Grafana. Plan chưa ghi nguồn dữ liệu này.
10. **Atlas Admin API:** executor DB gọi Atlas trong VPC nên cần NAT/IP allowlist của Atlas. Rate limit cũng cần tính tới (cross-module có nhắc 100 req/phút/IP).

---

## 4. Bảng quyết định Interlock đề xuất (bổ sung vào plan)

| `detail-type` | L1 | L2 | Gate `GREEN` | Gate `YELLOW` | Gate `RED` | Gate `UNKNOWN` | Trong giờ thi | Ghi chú |
| :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :--- |
| `atlas.tier.scale` (lên) | 403 | ✔ | ✔ | ✔ | ✔ | 409 | **409** trừ `EMERGENCY_OVERRIDE` | Override: chờ chốt 1 hay 2 SRE |
| `atlas.tier.scale` (xuống) | 403 | ✔ | Safety Gate 5/5 | 409 | 409 | 409 | **409** (trước 21:45) | |
| `atlas.iops.update` | 403 | ✔ | ✔ | ✔ | ✔ | 409 | **409** trừ override | Thiếu trong plan |
| `atlas.ops.kill_slow_queries` | 403 | ✔ (2 bước) | ✔ | ✔ | ✔ | ✔ | ✔ | Cứu hộ, không idempotent |
| `atlas.rs.step_down` | 403 | ✔ (2 bước) | ✔ | ✔ | ✔ | ✔ | ✔ | Cứu hộ, không idempotent |
| `lambda.concurrency.set_reserved` (tăng) | 403 | ✔ | ✔ (≤ 3.000) | ✔ (≤ 3.000) | 409 | 409 | ✔ | Thiếu trong plan |
| `lambda.concurrency.set_provisioned` (tăng) | 403 | ✔ | ✔ | ✔ | 409 | 409 | ✔ | |
| `lambda.circuit_breaker.mute_event_monitor` | 403 | ✔ (2 bước) | ✔ | ✔ | ✔ | ✔ | ✔ | Cứu hộ |
| `asg.capacity.update` (scale out) | 403 | ✔ | ✔ | *chốt* | 409 | 409 | ✔ | Plan chặn cả Vàng |
| `asg.capacity.update` (scale in) / `asg.scale_in.resume` | 403 | ✔ | Safety Gate 5/5 | 409 | 409 | 409 | **409** (trước 21:45) | |
| `alb.maintenance_503.toggle` | 403 | ✔ (2 bước) | ✔ | ✔ | ✔ | ✔ | ✔ | Cứu hộ |
| `cloudflare.waiting_room.toggle` | 403 | ✔ (2 bước) | ✔ | ✔ | ✔ | ✔ | ✔ | Cứu hộ |
| `ack` / `mute` / `request_sop` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | Không gửi lên bus điều khiển |

Executor phải kiểm tra lại các ô 409 (B5).

---

## 5. Kiểm chứng trích dẫn trong plan (Evidence)

- **Commit trích dẫn** `167aed9…` **không tồn tại** trong repo GitLab. Repo hiện chỉ có `6518515 Initial commit`. Plan được sinh từ `D:\Edmicro\DevSecOps\DevOpsThiSo` rồi mới import sang.
- **Đường dẫn đã đổi:** `BaoCaoSauThi.md`, `plan-exam.md`, `PlanConfigDay2.md`, `TinhHuong.md` nay ở `data-2-5.11.2026/`. `monitor-demo.html` nay ở `demo/`. `monitoring-overview-dashboard.md` nay ở `docs/specs/2026-11-12-spec-monitoring-overview-dashboard.md`. Toàn bộ manifest SHA-256 vì thế không còn kiểm tra được.
- **Số dòng trích dẫn lệch** khi so với bản spec trong `docs/specs/`. Lúc plan được sinh, file gốc đang ở trạng thái untracked nên có thể khác:
  - `:355-361` được ghi là "3 Interlocks", nhưng thực tế là sơ đồ ASCII 5 khối; Interlock nằm ở **365–371**.
  - `:295-315` được ghi là `PutEvents`, nhưng thực tế ở **305–325**.
  - "Audit 180 ngày `[verified theo :248-362]`": yêu cầu 180 ngày nằm ở **dòng 406**.
- **Trích dẫn đúng:** `BaoCaoSauThi.md:117-124` (ma trận quy mô); sự cố `schemaLock` 24,3s tại `plan-exam.md:45-53, 149`; Tab 3 demo tại `monitor-demo.html:1025` (`panel-control`); `<dialog>` không có `role`/`aria-modal` và `autofocus` nút Hủy (`:1176-1195`); `@container (width < 600px)` (`:586`).

**Đề xuất:** Sinh lại plan trên commit hiện tại, cập nhật đường dẫn và số dòng, bỏ manifest cũ.

---

## 6. Bổ sung Test Strategy

Giữ 5 test hiện có (sửa test 3 theo B2), thêm:

1. **`test_gate_no_alerts_stays_green`**: 10 phút không có webhook nhưng poll Grafana vẫn thành công → gate vẫn `GREEN`, không khóa nhầm (B3).
2. **`test_gate_unknown_allows_rescue`**: Grafana timeout quá 90s → `UNKNOWN`. Scale out, tier và scale down nhận 409. `mute_event_monitor`, `kill_slow_queries`, `503`, `waiting_room` vẫn được chạy với 2 bước xác nhận (B4).
3. **`test_l1_cannot_putevents`**: L1 gọi mọi `detail-type` hạ tầng, kể cả `preset`, đều nhận 403. `request_sop` không tạo event trên `edmicro-exam-ops-bus` (B2).
4. **`test_executor_rechecks_gate`**: event hợp lệ lúc gửi nhưng gate chuyển `RED` trước khi executor chạy → executor từ chối, trạng thái `REJECTED_INTERLOCK` (B5).
5. **`test_scheduler_scale_down_skipped_when_gate_not_met`**: lịch 21:45 chạy khi Dirty Cache 18% → `SKIPPED_GATE_NOT_MET`, ASG không đổi (B5).
6. **`test_expired_event_rejected`**: event quá `expires_at_utc` → `EXPIRED_STALE`, không gọi API (M1).
7. **`test_non_idempotent_crash_ambiguous`**: `rs.stepDown` crash giữa chừng, lease hết hạn → `AMBIGUOUS_MANUAL_CHECK`, không chạy lại (M2).
8. **`test_scheduler_vs_manual_mutex`**: Scheduler và L2 cùng tác động `examination-lambda` → chỉ một lệnh chạy, lệnh kia chờ hoặc bị từ chối có ghi lý do (M2).
9. **`test_reserved_cap_3000`**: yêu cầu `Reserved = 3.500` → 409 ở `/control` **và** bị từ chối ở executor (M5).
10. **`test_iops_locked_in_exam_window`** (M5).
11. **`test_webhook_hmac_and_replay`**: sai chữ ký → 401; timestamp lệch quá 5 phút → 401 (M7).
12. **`test_audit_append_only`**: chuỗi trạng thái tạo nhiều bản ghi; role của app không có quyền `UpdateItem/DeleteItem` (M6).
13. **`test_preset_fanout`**: preset `~60K` tạo đúng N lệnh con với `parent_action_id` chung, Dry-Run hiển thị đủ N thay đổi (M4).

---

## 7. Câu hỏi cần chốt trước khi sửa plan

1. **Ranh giới repo:** đồng ý theo cross-module (Control Panel và External Executor nằm ngoài `DevOpsThiSo`)? Nếu đồng ý thì plan Module 3 chỉ còn là spec, hoặc phải chuyển sang repo mới.
2. **`EMERGENCY_OVERRIDE`:** 1 SRE kèm lý do, hay cần 2 SRE ký duyệt (four-eyes)? Khuyến nghị: **2 SRE** cho `atlas.tier.scale/iops.update` trong giờ thi, vì đây đúng là kịch bản gây sự cố 29/10.
3. **Mức chặn scale out EC2/Lambda:** chặn ở Vàng (plan) hay chỉ chặn ở Đỏ (spec)?
4. **Cửa sổ giờ thi:** lấy từ đâu (lịch ca thi trong DynamoDB, file cấu hình, hay Grafana annotation P1/P2)?
5. **IdP SSO:** Cognito hay Google Workspace OIDC, và claim group cụ thể là gì?
6. **Phiên bản Grafana:** contact point webhook có hỗ trợ HMAC không, hay cần bridge?

---

## 8. Việc cần làm để plan sẵn sàng triển khai

- [ ] Viết lại §6 và §10 theo ranh giới repo và RACI của cross-module (B1).
- [ ] Sửa RBAC L1 theo spec §7.1, sửa test 3 (B2).
- [ ] Thiết kế lại Gate Sync: poll là nguồn chính, webhook để cập nhật nhanh, TTL 90s, trạng thái `UNKNOWN` (B3, B4).
- [ ] Đưa interlock cứng xuống executor và xử lý luồng Scheduler (B5).
- [ ] Nâng payload lên `PutEvents` v2 và thêm bảng ánh xạ `detail-type → Rule → Executor` (M1, M3).
- [ ] Chốt cách thực thi Preset (M4).
- [ ] Bổ sung bảng Interlock §4 vào plan (M5).
- [ ] Đổi Audit sang append-only (M6), webhook sang HMAC có chống replay (M7).
- [ ] Sinh lại plan trên commit `6518515` với đường dẫn và số dòng đúng (§5).
- [ ] Sửa `demo/monitor-demo.html`: Dry-Run mặc định bật, `Source`/`DetailType`/tên trường theo spec, xóa dòng audit mẫu L1 bật Provisioned.
