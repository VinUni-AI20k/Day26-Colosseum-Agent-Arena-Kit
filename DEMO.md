# DEMO — team undefeated (Day 26 · Colosseum)

Mọi lệnh chạy từ thư mục gốc repo trong **Windows PowerShell**. Máy không có `make`, nên dùng các lệnh tương đương bên dưới.

## 0. Chuẩn bị (một lần)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pytest
gh release download world-df8c55dabb35 --pattern '*.zip'   # nếu kit/world/df8c55dabb35/ chưa có
Expand-Archive colosseum-world-df8c55dabb35.zip -DestinationPath .
```

## 1. Demo một lệnh

```powershell
powershell -ExecutionPolicy Bypass -File .\demo.ps1               # đủ 7 bước, cuối cùng mở màn hình replay
powershell -ExecutionPolicy Bypass -File .\demo.ps1 -NoUI         # không mở replay
powershell -ExecutionPolicy Bypass -File .\demo.ps1 -Bot operator -Seed 2
```

| Bước | Nội dung trình bày | Kết quả mong đợi |
|---|---|---|
| 1 | Sẵn sàng (`make doctor`) | G-KEY PASS · 17 lớp lỗi · validate 0 FAIL |
| 2 | **DEFEND**: gateway xử lý 9 lệnh mẫu | lệnh sạch được `forward`/`rewrite` (ghim replica, đổi tool deprecated, thu hẹp mask); 6 lệnh tấn công bị `deny`, mỗi lệnh kèm lý do |
| 3 | **Answer side**: `vet_answer` trên một bản nháp bị đầu độc | anchor bịa bị bỏ, email bị che, chỉ thị bị chèn được báo ra thay vì làm theo |
| 4 | **PROSECUTE** trên 40 fixture có nhãn | precision 1.000 · recall 1.000 · false 0 |
| 5 | Đấu với 3 bot | thắng rookie 100–0, operator 100–0, adversary 72–0 |
| 6 | Báo cáo trận với adversary | đọc danh sách **MISSED**, không chỉ nhìn HP |
| 7 | Replay pixel tại `http://localhost:8765/?run=spar-adversary-1` | xem 5 ô QUESTION → ACTION → ANSWER → EVAL → REFEREE theo từng hiệp |

Màn hình replay: hàng **YOU DEFEND** là gateway của đội. Ô 2 (ACTION) cho thấy lệnh nào bị `DENIED`; ô 5 (REFEREE) cho thấy bên nào mất máu và vì sao.

## 2. Lệnh rời để tự đánh giá

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest tests/ -q                               # conformance (make test)
.\.venv\Scripts\python.exe spar.py --bot operator --as defender             # chỉ đo vai phòng thủ
.\.venv\Scripts\python.exe spar.py --bot adversary --as prosecutor          # công tố: không được có FALSE
.\.venv\Scripts\python.exe spar.py --bot rookie --as all --seed 3 --ui      # ghi log trận để xem replay
.\.venv\Scripts\python.exe -m kit.arena_ui.serve --run spar-rookie-3       # mở replay của trận vừa ghi
.\.venv\Scripts\python.exe -m eval.prosecute                                # điểm công tố trên fixture
.\.venv\Scripts\python.exe -m agent.gateway; .\.venv\Scripts\python.exe -m agent.guardrails   # self-test từng file
```

Lưu ý: ở `--as attacker`/`--as prosecutor`/`--as defender`, các vai còn lại do **bot** đảm nhận. Ví dụ `--as attacker` dùng prosecutor của bot, nên vẫn 100–100 với rookie vì prosecutor của rookie không bao giờ buộc tội ("no claim, no damage"). Muốn đo cả đội thì dùng `--as all`.

## 3. Checklist đánh giá

- [ ] `make test`: chỉ được fail đúng `test_isolation::test_run_probe_vectors_unsandboxed_baseline`. Test này dò sandbox macOS bằng `ctypes`, nên fail trên Windows ngay cả với kit gốc chưa sửa.
- [ ] validate 0 FAIL; `git status kit/ bots/ fixtures/` không có thay đổi.
- [ ] Spar `--as all`: thắng cả 3 bot với mọi seed thử.
- [ ] Bảng claim mỗi hiệp: không có claim FALSE.
- [ ] Mỗi lần `deny` trong replay đều có lý do cụ thể, và lá trống (`blk_*`) không bị từ chối oan.
- [ ] Sửa `agent/`, `deck/` hay `eval/` thì phải đóng gói lại bundle và chép vào thư mục nộp:
  `.\.venv\Scripts\python.exe -m kit.submit --team undefeated; Copy-Item submissions\undefeated.bundle K4-DAY26-undefeated\`

## 4. Có thể bổ sung (đề xuất, chưa làm)

| Ý tưởng | Lợi ích | Ghi chú |
|---|---|---|
| Ghi nhớ etag từ `registry.provenance` vào gateway (`note_provenance`) rồi tự gắn `If-Match` cho lệnh ghi | ghi hợp lệ thay vì bị từ chối | cần nơi gọi `note_provenance`; bản hiện tại chỉ dựa trên `cmd`/`ctx` |
| Rút xác suất drift theo `path_id` vào `pick_replica` (`known_drifting`) | chống `stale_read` / `replica_flip` tốt hơn | dùng tập 16 path_id drift đã nhúng trong `eval/prosecute.py` |
| Ngân sách theo hệ số vòng (dành credit cho vòng ×1.5) | ít bị cạn credit ở cuối trận | giống `_ROUND_ALLOWANCE` của bot adversary |
| Thêm 1–2 lá tấn công mới nhắm path_id drift khác (vd `0e11ae43`, delta 34) | thay atk_02/03 vốn chưa hạ được adversary | phải chạy lại `validate` và đo lại bằng spar |
| Bộ fixture riêng cho detector ngữ nghĩa | tránh overfit vào 40 fixture mẫu | 8 lớp ngữ nghĩa ở giải thật do model chấm |
