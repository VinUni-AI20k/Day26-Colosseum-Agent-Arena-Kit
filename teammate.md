# Team: undefeated

| Họ tên | MSSV | Vai trò |
|---|---|---|
| Đỗ Quang Vinh | 2A202602989 | Cả ba vai: ATTACK (`deck/`), DEFEND (`agent/`), PROSECUTE (`eval/`) |

Đội 1 thành viên — K4 · Track 2 · Day 26 (Colosseum Agent Arena).
Thư mục nộp: [`K4-DAY26-undefeated/`](K4-DAY26-undefeated/), gồm `TEAMMATES.md` và `undefeated.bundle`.

## Đã làm

- **Bước 4 — gateway (`agent/gateway.py`):** cài bốn job. Mỗi lệnh chỉ bị chặn khi có một dấu hiệu cụ thể nhìn thấy được, và `decide()` không bao giờ ném exception (lỗi nội bộ thì từ chối).
  - **ROUTE:** chặn route trong body; chuyển `slides.search` sang `slides.query`; ghim `Mcp-Replica` vào header.
  - **ADMIT:** chặn `get_frame` không có lease sống, chỉ thị bị chèn, server/Agent Card giả, peer chưa kiểm chứng, payload phình to, và lệnh lặp lại y hệt một lệnh đã lỗi.
  - **AUTHORIZE:** target phải đúng `ctx.act`; `aud` phải khớp server; lệnh ghi cần scope, `If-Match` và `Idempotency-Key` chưa dùng.
  - **BUDGET:** mask rẻ cho các tool "nút tự phạt"; giữ credit dự trữ cho các vòng sau.
- **Bước 5 — câu trả lời trung thực:**
  - `agent/guardrails.py`: `scan_for_injected_instructions` (mẫu tiếng Anh và tiếng Việt), `redact` (đoạn ≥ 40 ký tự chép từ nguồn riêng tư, email, số điện thoại, secret), `verify_arithmetic` (phép tính sai; số liệu không có nguồn hoặc chính xác hơn nguồn), `abstention_policy` (sửa câu trả lời thay vì từ chối; không từ chối lá trống), và `vet_answer` chạy cả chuỗi.
  - `agent/prompt.md` viết lại cho model: kế hoạch 4 lượt / 20 giây / 100 credit, playbook cho 8 loại câu hỏi, quy tắc dẫn nguồn, chính sách từ chối, cách xử lý hai nguồn mâu thuẫn.
- **Bước 6 — bộ bài:** mọi lá tấn công đều khai `defense_event: gateway.denied`. Lineup xếp lại theo sát thương đo được: lá yếu ở vòng ×1.0, các lá xuyên được adversary để dành cho vòng ×1.5, và thêm `blk_02` ở vòng 4 làm mồi. Chi tiết trong `deck/README.md` §4.
- **Bước 7 — công tố (`eval/prosecute.py`):** cài đủ 16 detector. Trên 40 fixture có nhãn đạt precision 1.000, recall 1.000, 0 cáo buộc sai. Trong spar, 30/30 lượt buộc tội không có cáo buộc FALSE nào.

## Chức năng bổ sung (sau Bước 8)

1. **Etag cho lệnh ghi:** gateway nhớ etag từ `registry.provenance` (qua `note_provenance` hoặc `ctx.history`) và tự gắn `If-Match`.
2. **Replica theo drift đo được:** ở cả 16 deck có drift, bản working đều đầy đủ hơn canonical, nên mình đọc theo `DRIFT_TABLE`. Header mâu thuẫn với `/rev/` của anchor sẽ bị chặn.
3. **Ngân sách theo hệ số vòng:** 8 / 10 / 11 credit. Lệnh tùy chọn được hoãn sang vòng sau; lệnh cốt lõi vẫn cho qua.
4. **Hai lá bài mới:** atk_02 nhắm `0e11ae43` hỏi về `Concept:rlhf/w/042` (được dạy cả ngày 11 lẫn ngày 22); atk_03 nhắm `7a8d8046`, deck có drift lớn nhất.
5. **`eval/selfcheck.py`:** 13 fixture riêng (có tiếng Việt và 5 bẫy sạch) đạt 13/13, 0 sai. Bộ này giúp phát hiện và sửa một chỗ hụt của detector `guardrail_breach` với câu tuân lệnh bằng tiếng Việt.

Hướng dẫn demo: [`DEMO.md`](DEMO.md) · chạy một lệnh: `powershell -ExecutionPolicy Bypass -File .\demo.ps1`

## Kiểm tra (Bước 8)

| Mục | Kết quả |
|---|---|
| `make test` | 4608 passed, 1 failed — `test_isolation::test_run_probe_vectors_unsandboxed_baseline` dùng `ctypes` để thăm dò sandbox macOS (`sandbox-exec`) và không chạy được trên Windows. Test này fail cả trên bản kit gốc chưa sửa, không liên quan code của đội. |
| `make validate` | 0 FAIL (1 WARN về lethality band — validator chỉ kiểm được gần đúng) |
| `git status kit/ bots/ fixtures/` | không có thay đổi |
| Import cấm / G-KEY | `kit.submit` không báo lỗi; G-KEY PASS |
| Bundle | `submissions/undefeated.bundle` (bản sao nằm trong `K4-DAY26-undefeated/`) |

## Đấu thử (`spar.py --as all`, seed 1–3)

| Bot | Kết quả |
|---|---|
| rookie | thắng 100–0 (cả 3 seed) |
| operator | thắng 100–0 (cả 3 seed) |
| adversary | thắng 72–0, 48–3, 72–0 |

Máu bị mất khi đấu adversary đều đến từ `fabricated_citation`. Lỗi này do harness của spar tự chèn một anchor ngẫu nhiên vào câu trả lời (xác suất 35%), gateway không cho lọt lệnh nào.

*Có dùng AI:* Claude Code (Claude Opus 5.5) hỗ trợ đọc kit, viết gateway / guardrails / detector / prompt và chạy kiểm thử. Tôi đã review và giải thích được mọi thay đổi. Không đưa trace của đối thủ cho AI trong giải đấu.
