# scale-api — nút "Bấm để scale" trên Grafana

Grafana (row **Bấm để scale** trong `grafana-system-health-v2.json`) → Infinity datasource (giữ token) → API Gateway `POST /scale` → Lambda `scale-api` → EC2 Auto Scaling / Lambda Reserved Concurrency / MongoDB Atlas.

## Nút làm gì

Mỗi bảng (MongoDB, Auto Scaling, Lambda) có 4 nút preset: **Ngày thường · < 10K · < 30K · ~60K**. Bấm một ô trong bảng → chọn mức → hộp xác nhận hiện đúng giá trị sẽ đặt → Xác nhận. Giá trị nằm trong `PRESETS` ở `handler.py`.

| Mức | cluster-exam / Cluster1 | examination / oauth (Reserved) | api / oauth / datawrk (Min-Desired-Max) |
|:--|:--|:--|:--|
| Ngày thường | M10 / M20 | 200 / 50 | 2-4-20 · 2-2-10 · 2-2-10 |
| < 10K | M40 / M40 | 1.000 / 200 | 15-15-30 · 8-8-15 · 2-2-10 |
| < 30K | M50 / M50 | 2.000 / 300 | 25-25-50 · 15-15-25 · 2-2-10 |
| ~60K | M60 (10K IOPS) / M60 | 3.000 / 500 | 40-40-70 · 25-25-30 · 2-2-10 |

Giá trị MongoDB và Lambda lấy từ `BaoCaoSauThi.md`; ASG mức ~60K theo spec §6.2. **Các dòng ASG ghi `# DUYỆT` trong `handler.py` là ước lượng — SRE cần xác nhận trước khi dùng.** "Khóa scale-in" được làm bằng `Min = Desired` (ASG vẫn tự thay máy lỗi).

## Chốt an toàn (API tự từ chối, trả 409 + lý do, báo Slack)

- **Tăng máy hoặc tăng Lambda** khi Scaling Gate của DB thi đang LOCK (CPU ≥ 75%, kết nối ≥ 25K, dirty ≥ 20%, hàng đợi ghi > 10). Không đọc được Prometheus cũng coi là LOCK.
- **Đổi tier MongoDB** trong khung giờ thi (`ExamWindows`, mặc định 15:00–21:45), khi cụm chưa `IDLE`, hoặc **hạ tier** khi dirty cache ≥ 15%.
- **Hạ số máy** trong khung giờ thi.
- Vượt trần cứng: examination ≤ 3.000, oauth ≤ 500, ASG Max ≤ 70, tier M10–M60.
- Quyền IAM chỉ đúng 3 ASG và 2 hàm Lambda; cấm mọi thao tác Delete/Terminate.

Mọi lệnh (kể cả bị chặn) ghi log JSON vào `/aws/lambda/scale-api` (giữ 180 ngày) kèm người bấm (`${__user.login}`).

## Deploy (người có quyền CloudFormation, Lambda, IAM, API Gateway, Secrets Manager)

```bash
cd scale-api
aws cloudformation package --template-file template.yaml --s3-bucket <bucket-chứa-artifact> --output-template-file packaged.yaml
aws cloudformation deploy --template-file packaged.yaml --stack-name scale-api --capabilities CAPABILITY_NAMED_IAM \
  --region ap-southeast-1 \
  --parameter-overrides PromUrl=http://<prometheus-nội-bộ>:9090 SlackWebhookUrl=<webhook> \
                        SubnetIds=<subnet-có-NAT> SecurityGroupIds=<sg-vào-được-prometheus>
```

Sau đó:
1. Điền Atlas API key vào secret `scale-api/atlas`: `{"public_key":"…","private_key":"…","group_id":"<Atlas project id>"}`. Key cần quyền **Project Cluster Manager**; thêm IP NAT của Lambda vào Atlas API access list.
2. Lấy token: `aws secretsmanager get-secret-value --secret-id scale-api/token --query SecretString`.
3. Thử trước bằng dry-run (không thay đổi gì):
   ```bash
   curl -X POST <ScaleUrl> -H "X-Scale-Token: <token>" -H "Content-Type: application/json" \
        -d '{"target":"asg","preset":"60k","user":"test","dry_run":true}'
   ```

## Cấu hình Grafana

1. Cài plugin **Infinity** (`yesoreyeram-infinity-datasource`) và tạo một datasource Infinity riêng, ví dụ tên `scale-api`:
   - **Allowed hosts:** `https://<api-id>.execute-api.ap-southeast-1.amazonaws.com`
   - **Custom HTTP header:** `X-Scale-Token` = token ở bước 2 (lưu dạng secure, không lộ ra trình duyệt).
2. Trong `grafana-system-health-v2.json` thay 2 giá trị rồi import lại:
   - `REPLACE_INFINITY_DS_UID` → UID của datasource Infinity vừa tạo.
   - `REPLACE_API_ID` → API id trong output `ScaleUrl`.
3. **Giới hạn quyền:** ai xem được dashboard là bấm được nút. Đặt dashboard trong folder chỉ nhóm SRE/DevOps có quyền xem; đội trực thi dùng một bản dashboard không có row "Bấm để scale".
4. Nếu Grafana không hiện nút khi bấm vào ô bảng: kiểm tra tính năng Actions đã bật (feature toggle `vizActions` / `vizActionsAuth` ở các bản Grafana cũ hơn).

## Test

`handler.py` có 11 test đơn vị (mock AWS/Atlas/Prometheus): sai token, preset sai, tăng ASG, chặn khi Gate LOCK, chặn hạ máy trong giờ thi, mất Prometheus thì chặn, trần Lambda, dry-run không ghi, Atlas trong giờ thi / ngoài giờ thi / chưa IDLE.
