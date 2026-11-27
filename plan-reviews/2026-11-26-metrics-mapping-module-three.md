# Khớp Metrics — Module 3 (plan v2) ↔ Từ điển Chỉ số

| | |
| :--- | :--- |
| **Từ điển chuẩn** | `docs/specs/dashboard-metrics-dictionary.md` (commit `6518515`), gọi tắt là **TĐ** |
| **Đối chiếu thêm** | Spec `docs/specs/2026-11-12-spec-monitoring-overview-dashboard.md` §5, §6.2, §8.2 · Plan Module 1 dòng 44–51 (recording rules, `ScalingGateLock`, `SafetyScaleDownOk`) · `demo/monitor-demo.html:1698–1700` |
| **Bên dùng** | [Plan Module 3 v2](2026-11-26-plan-module-three-eventbridge-control-v2.md) |
| **Nguyên tắc** | Module 3 **không tự tính ngưỡng**. Metric đi vào Grafana alert rule (Module 1), Module 3 chỉ đọc trạng thái rule. Vì vậy file này xác định: rule nào, metric nào theo mã TĐ, ngưỡng nào |

Ký hiệu trạng thái: ✅ khớp · ⚠️ lệch giữa các tài liệu (đã chọn giá trị) · ➕ thiếu trong v2 (đã bổ sung) · 📝 cần bổ sung vào TĐ hoặc Module 1

---

## 1. Bảng khớp tổng hợp

| Module 3 dùng cho | Mã TĐ | Metric (tên Atlas/AWS · recording rule Module 1) | Ngưỡng theo TĐ | Dùng trong v2 | TT |
| :--- | :-: | :--- | :--- | :--- | :-: |
| **Scaling Gate** (toàn bộ) | 5.4 | Rule `ScalingGateLock` | `OK` / `CAUTION` / `LOCK` | Gate `scaling` = `GREEN/YELLOW/RED` | ⚠️ §2 |
| Gate — CPU DB | 4.3 | `SYSTEM_NORMALIZED_CPU_*` | LOCK ≥ 75% (5.4); Đỏ > 80% (4.3) | Điều kiện LOCK | ⚠️ §2 |
| Gate — Write IOPS | 4.4 | `DISK_PARTITION_IOPS_WRITE` / 10.000 | LOCK ≥ 80% (5.4); Đỏ > 85% (4.4) | Điều kiện LOCK | ⚠️ §2 |
| Gate — Connections | 4.1 | `CONNECTIONS` / 32.000 | LOCK ≥ 25K (5.4 = 4.1 Đỏ) | Điều kiện LOCK | ✅ |
| Gate — Dirty Cache | 4.5 | `exam:wiredtiger_dirty_cache_pct` | Đỏ > 20% (TĐ 5.4 không liệt kê) | Điều kiện LOCK | 📝 |
| Gate — Writers Queue | 4.6 | `GLOBAL_LOCK_CURRENT_QUEUE_WRITERS`, `TICKETS_AVAILABLE_WRITES` | Đỏ: Queue > 10 hoặc Tickets < 32 | Điều kiện LOCK | ➕📝 |
| Gate — Write Latency | — | Atlas `OP_EXECUTION_TIME_WRITES` | Spec §5: Đỏ > 30 ms | Điều kiện LOCK | ➕📝 |
| Gate — Connection Churn | 4.2 | Δ`CONNECTIONS`/phút, TLS handshake ms | Đỏ > 5.000/phút hoặc TLS > 150 ms → "khóa tăng VM/Lambda" | Điều kiện LOCK | ➕📝 |
| **Safety Scale-Down Gate** | 5.5 | Rule `SafetyScaleDownOk` + kiểm tra ở executor | Đủ 5/5 | Gate `scale_down = OK/LOCK` | ⚠️ §3 |
| Scale-down — giờ | 5.5 (1) | Thời gian VN ≥ `hard_end` (21:45) | ≥ 21:45 | Control API và executor | ✅ |
| Scale-down — IDLE | 5.5 (2) | Atlas cluster `stateName = IDLE` (TĐ 4.8) | `IDLE` | Executor gọi Atlas API | ✅ |
| Scale-down — Dirty | 5.5 (3) | `exam:wiredtiger_dirty_cache_pct` | < 15% | Rule `SafetyScaleDownOk` | ✅ |
| Scale-down — Cooldown | 5.5 (4) | Thời gian từ lệnh scale thành công gần nhất trên target | ≥ 15 phút | Executor đọc `ops-audit` | ⚠️ §3 |
| Scale-down — SQS | 5.5 (5) · 2.7 | SQS `ApproximateNumberOfMessagesVisible` (queue `event-monitor`) | = 0 | Rule `SafetyScaleDownOk` | ✅ |
| Scale-down — CPU | — | `SYSTEM_NORMALIZED_CPU_*` | Spec §6.2 "CPU < ngưỡng"; demo < 25% | v2 cũ có; **bỏ** để khớp TĐ | ⚠️📝 |
| Scale-in ASG — Unhealthy | 1.7 | ALB `UnHealthyHostCount` (`api-elb`, `oauth`) | > 0 thì **không cho Scale In** | Điều kiện bổ sung cho scale-in ASG | ➕ |
| **Khóa tier/IOPS DB** | 4.8 | Atlas Replica State, Oplog lag, rolling update | Khóa cả ca; nâng cấp phải xong trước `T-4h` | Cửa sổ `db_change_lock` | ⚠️ §4 |
| Tier/IOPS — không chạy chồng | 4.8 | Atlas `stateName ≠ IDLE` | Đang rolling update thì Đỏ | Executor từ chối nếu ≠ `IDLE` | ➕ |
| **Trần cứng Lambda** | 2.1 | `PutFunctionConcurrency` (giá trị cấu hình) | `examination` Reserved 3.000, Provisioned 1.200; `oauth` 500 | Giới hạn cứng §6.3 | ✅ |
| **Trần cứng ASG** | 3.1 | ASG `MaxSize` | `api-elb` 38–50, trần 60–70; `oauth` 22–25 | `api-elb ≤ 70`, `oauth ≤ 30` | ⚠️ (TĐ không ghi trần riêng cho oauth; 30 lấy từ spec §7.2) |
| **Bật lại `event-monitor`** | 2.7 | SQS depth, `OldestMessageAge` | Chỉ xả **sau 21:45 khi DB Xanh**, Reserved 50–100 | v2 cũ cho phép bất kỳ lúc nào | ➕ |
| **Banner độ tin cậy bus** | 5.6 | `FailedInvocations` của bus + số message trong DLQ | `0` / `1` / `≥ 2` | v2 cũ chỉ có DLQ | ➕ |
| **Pre-Exam Readiness** | 5.3 | 4 điều kiện boolean | `4/4` / `3/4` / `≤ 2/4` (cấm phát đề) | v2 cũ không dùng | ➕ §5 |
| Provisioned sẵn sàng | 5.3 (2) · 2.2 | `PutProvisionedConcurrencyConfig` → trạng thái `READY` | 1.200 trước P1/P2 `T-15m` | Lịch chạy sớm hơn để kịp `READY` | ➕ §5 |
| Lệnh cứu hộ S4 | 2.3 | `Throttles/min` | Đỏ > 10/phút (TĐ); spec §8.2 > 100/phút | Chỉ hiển thị (L2 tự quyết) | ⚠️ (hiển thị, không ảnh hưởng gate) |
| Lệnh cứu hộ S5 | 1.5 | Waiting Room queue, wait time | Đỏ > 500 người hoặc > 2 phút | Chỉ hiển thị | ✅ |

---

## 2. Scaling Gate: chọn một bộ ngưỡng duy nhất

Năm nguồn đang định nghĩa điều kiện "khóa scale out" khác nhau:

| Điều kiện | TĐ 5.4 | TĐ tầng 4 (Đỏ) | Spec §5 (Đỏ) | Spec §6.2 (guardrail ASG) | Module 1 `ScalingGateLock` | Demo |
| :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| CPU DB | ≥ 75% | > 80% | > 80% | — | ≥ 75% | ≥ 75% |
| Write IOPS | ≥ 80% | > 85% | > 85% | — | ≥ 80% | ≥ 8.000 |
| Connections | ≥ 25K | > 25K | > 75% (24K) | — | ≥ 25K | ≥ 25.000 |
| Dirty Cache | — | > 20% | — | — | ≥ 20% | ≥ 20% |
| Writers Queue | — | > 10 | > 10 | > 10 | — | — |
| Write Latency | — | — | > 30 ms | > 30 ms | — | — |
| Conn Churn / TLS | — | > 5.000/phút hoặc > 150 ms | — | — | — | — |
| CPU `Cluster1` | — | — | — | — | — | ≥ 85% |

**Bộ ngưỡng chọn cho `ScalingGateLock` (gate `RED`):** kích hoạt khi **bất kỳ** điều kiện nào sau đây đúng trên `cluster-exam`, kéo dài `for: 30s`:

| # | Điều kiện | Mã TĐ | Lý do chọn |
| :-: | :--- | :-: | :--- |
| 1 | CPU ≥ 75% | 4.3 / 5.4 | Theo TĐ 5.4. Gate cố ý khóa **sớm hơn** mức Đỏ của alert (80%) |
| 2 | Write IOPS ≥ 80% (8.000/10.000) | 4.4 / 5.4 | Như trên |
| 3 | Connections ≥ 25.000 | 4.1 / 5.4 | Mọi nguồn đều khớp |
| 4 | Dirty Cache ≥ 20% | 4.5 | WiredTiger tự hãm ghi từ 20%. Module 1 và demo đã có |
| 5 | Writers Queue > 10 **hoặc** Tickets ghi < 32 | 4.6 | Spec §6.2 dùng đúng điều kiện này cho guardrail ASG |
| 6 | Write Latency > 30 ms | — | Spec §5 và §6.2. Cần thêm vào TĐ |
| 7 | Conn Churn > 5.000/phút **hoặc** TLS > 150 ms | 4.2 | TĐ 4.2 yêu cầu "khóa ngay tăng VM/Lambda burst" |

**Rule mới `ScalingGateCaution` (gate `YELLOW`):** dùng khoảng Vàng của TĐ: CPU 65–75%, IOPS 70–80%, Conn 15K–25K, Dirty 15–20%, Writers Queue 1–10 hoặc Tickets 32–95, Churn 2K–5K/phút. Module 1 hiện **chưa có** rule này.

**Cách gọi tên trạng thái:**

| TĐ 5.4 / Dashboard (Module 2) | Module 3 v2 / cross-module |
| :--- | :--- |
| `OK` | `GREEN` |
| `CAUTION` | `YELLOW` |
| `LOCK` | `RED` |
| *(không có)* | `UNKNOWN`: mất Grafana quá 90s. Dashboard nên hiển thị là `LOCK (Không rõ)` |

**`Cluster1`:** không đưa vào Scaling Gate, vì TĐ 5.4 chỉ xét DB thi. Sự cố `Cluster1` xử lý theo nhánh S3 (503 hệ thống học), là lệnh cứu hộ không bị gate chặn.

---

## 3. Safety Scale-Down Gate: theo TĐ 5.5 (5/5)

| # | Điều kiện TĐ 5.5 | Ai kiểm tra | Ghi chú |
| :-: | :--- | :--- | :--- |
| 1 | Sau 21:45 | Control API và executor (`hard_end` của ca) | Không đưa vào Grafana rule (Module 1 đang dùng `hour >= 21.75`; nên bỏ để tránh lệch múi giờ) |
| 2 | `IDLE` | Executor gọi Atlas Admin API (`stateName`) | Grafana không có sẵn trạng thái này |
| 3 | Dirty Cache < 15% | Rule `SafetyScaleDownOk` | |
| 4 | Cooldown ≥ 15 phút | Executor: thời điểm `SUCCEEDED` gần nhất của lệnh scale trên **cùng target** trong `ops-audit` | v2 cũ hiểu là `for: 15m`, nay sửa theo nghĩa cooldown kể từ lần scale gần nhất (khớp `SafetyChecker` của `AutoScalingMongo`) |
| 5 | SQS Backlog = 0 | Rule `SafetyScaleDownOk` (queue `event-monitor`) | |
| + | `UnHealthyHostCount == 0` (TĐ 1.7) | Executor (ALB API), **chỉ với scale-in ASG** | TĐ 1.7 cấm Scale In khi có host không khỏe |

- Rule `SafetyScaleDownOk` của Module 1 thu gọn còn: `Dirty < 15% AND SQS == 0`, kèm `for: 5m` để tránh dao động. Các điều kiện 1, 2, 4 do executor kiểm tra.
- **Bỏ điều kiện CPU < 25%** khỏi v2 để khớp TĐ. Spec §6.2 có nhắc "CPU < ngưỡng". Nếu muốn giữ, cần **thêm vào TĐ 5.5** thành điều kiện (6) có ngưỡng cụ thể. 📝
- **Thứ tự sau 21:45** (thêm vào lịch v2 §6.5), vì điều kiện (5) cần SQS rỗng nên phải xả hàng đợi trước khi hạ tải:
  1. 21:45 bật lại `event-monitor` (Reserved 50) khi gate `GREEN` (TĐ 2.7).
  2. Chờ SQS = 0.
  3. Các lịch hạ tải mỗi 5 phút chỉ thực hiện khi đủ 5/5.
  4. Nếu đến 22:40 SQS chưa rỗng, cho phép L2 tăng Reserved lên 100 (TĐ 2.7: 50–100).

---

## 4. Cửa sổ khóa tier/IOPS DB: theo TĐ 4.8

- **TĐ 4.8:** "KHÓA CỨNG nút Scale DB Tier trong suốt ca thi; mọi nâng cấp phải hoàn tất trước `T-4h`".
- **v2 cũ** dùng một cửa sổ chung `[t_start − 60 phút, hard_end]`, mở quá muộn so với TĐ.
- **Sửa:** tách hai cửa sổ:
  - `db_change_lock = [T-4h, hard_end]` áp cho `atlas.tier.scale` và `atlas.iops.update`.
  - `exam_window = [t_start − 60 phút, hard_end]` dùng cho các nội dung khác, ví dụ hiển thị.
- **Hệ quả cho Scheduler:** spec §6.2 đặt lịch scale up tier lúc **đúng** `T-4h (15:00)`, trùng ranh giới khóa. Lịch chuyển sang **`T-4h30` (14:30)** để rolling update xong trước 15:00. Readiness (1) xác nhận lúc `T-4h`. Cần sửa spec §6.2 tương ứng. 📝
- Executor từ chối `atlas.tier.scale/iops.update` khi Atlas `stateName ≠ IDLE` (TĐ 4.8: đang rolling update là Đỏ).

---

## 5. Pre-Exam Readiness Gate (TĐ 5.3): bổ sung vào `/control`

| # | Điều kiện TĐ 5.3 | Nguồn | Thời điểm kiểm tra |
| :-: | :--- | :--- | :--- |
| 1 | `cluster-exam` và `Cluster1` M60, `3/3 Healthy`, không rolling update | Executor `atlas.rolling_status.check` | Lịch `T-4h` và `T-45p` |
| 2 | `examination-lambda` Provisioned = 1.200 và trạng thái `READY` | Executor `lambda` (`GetProvisionedConcurrencyConfig`) | `P1 − 15p`, `P2 − 15p` |
| 3 | `api-elb ≥ 38`, `oauth ≥ 22`, đã `Suspend ScaleIn` | Executor `edge` (`DescribeAutoScalingGroups`) | `T-45p` + 5 phút |
| 4 | SQS và EventBridge DLQ = 0 | Grafana rule (TĐ 5.6) | Liên tục |

- Control API tạo thêm các lịch **chỉ kiểm tra** (`detail-type: readiness.check`, executor chỉ đọc). Kết quả hiển thị ở header `/control` dạng `4/4 | 3/4 | ≤2/4`.
- Khi `≤ 2/4`, gửi cảnh báo L2 "Cấm phát đề". `/control` **không tự chặn** việc phát đề vì đó không phải thao tác của Module 3.
- **Thời gian `READY` của Provisioned:** cấu hình 1.200 container cần vài phút để khởi tạo. Lịch bật Provisioned chuyển từ `19:15` sang **`19:00`** (P1) và từ `20:15` sang **`20:00`** (P2), để đạt `READY` trước mốc `T-15m` theo TĐ 2.2. Cần sửa spec §6.2. 📝

---

## 6. Metrics trong TĐ mà Module 3 chỉ hiển thị

Những metric sau không tham gia interlock, chỉ hiện trong Dry-Run Diff hoặc header `/control` (đọc qua `/api/ds/query`):

- **TĐ 1.1–1.4, 1.6** (người dùng, gateway, lỗi HTTP, client retry): giúp L2 chọn S4 hay S5.
- **TĐ 2.2, 2.3, 2.4** (scale velocity, throttles, duration): hiển thị khi bấm lệnh Lambda.
- **TĐ 3.2–3.4** (EC2, NAT, Redis): hiển thị khi bấm lệnh ASG. TĐ 3.3 và 3.4 không có lệnh điều khiển tương ứng trong Module 3.
- **TĐ 4.7** (COLLSCAN): hiển thị khi bấm `kill_slow_queries`.
- **TĐ 5.1, 5.2** (Socket Headroom, Saturation ETA): hiển thị trong Dry-Run của lệnh tăng Lambda hoặc ASG, kèm giá trị **dự báo sau thay đổi**: `(Reserved_mới × 2 × 3 + EC2_mới × 20) / 32.000`.

---

## 7. Việc cần làm

**Cập nhật vào plan v2** (đã sửa trong file plan):
- [x] Gate `scaling` đọc rule `ScalingGateLock` (RED) và `ScalingGateCaution` (YELLOW) thay cho label S1–S3 (§2).
- [x] Safety Scale-Down theo TĐ 5.5: bỏ CPU < 25%, cooldown tính từ lần scale gần nhất, thêm `UnHealthyHostCount` cho scale-in (§3).
- [x] Bật lại `event-monitor` chỉ sau 21:45 khi `GREEN`, giá trị 50–100 (§3).
- [x] Cửa sổ `db_change_lock = [T-4h, hard_end]` và yêu cầu Atlas `IDLE` (§4).
- [x] Readiness Gate 4/4, lịch Provisioned 19:00/20:00, lịch tier 14:30 (§5).
- [x] Banner bus dùng `FailedInvocations` và DLQ (TĐ 5.6).

**Đề xuất cho Module 1** (alert rules):
- [ ] `ScalingGateLock`: thêm điều kiện 5, 6, 7 ở §2.
- [ ] Rule mới `ScalingGateCaution`.
- [ ] `SafetyScaleDownOk`: thu gọn còn `Dirty < 15% AND SQS == 0`, `for: 5m`.
- [ ] Rule `EventBridgeBusUnhealthy` (TĐ 5.6).
- [ ] Gắn label `gate=scaling|scale_down|none` cho các rule.

**Đề xuất cho TĐ** 📝:
- [ ] TĐ 5.4 thêm Dirty ≥ 20%, Writers Queue/Tickets, Write Latency > 30 ms, Churn; ghi rõ gate khóa sớm hơn mức Đỏ của alert.
- [ ] Thêm dòng **Write Latency** vào tầng 4 (đang có trong spec §5 nhưng TĐ thiếu).
- [ ] TĐ 5.5: chốt có thêm điều kiện CPU hay không.
- [ ] Thống nhất ngưỡng **Throttles Đỏ**: TĐ 2.3 ghi > 10/phút, spec §8.2 (S4) ghi > 100/phút.
- [ ] Thống nhất **Connections Đỏ**: TĐ ghi > 25K (78%), spec §5 ghi > 75% (24K).

**Đề xuất cho spec §6.2:** lịch tier `T-4h30`, Provisioned `19:00`/`20:00`.
