# Team: undefeated

| Họ tên | MSSV | Vai trò |
|---|---|---|
| Đỗ Quang Vinh | 2A202602989 | Cả ba vai: ATTACK (`deck/`), DEFEND (`agent/`), PROSECUTE (`eval/`) |

Đội 1 thành viên — K4 · Track 2 · Day 26 (Colosseum Agent Arena).
Bundle nộp: `make submit TEAM=undefeated` → `submissions/undefeated.bundle`.

## Đã làm

- **DEFEND — `agent/gateway.py`:** cài bốn job, mỗi lệnh chỉ bị chặn khi có một dấu hiệu cụ thể nhìn thấy được trên `cmd`/`ctx`:
  - **ROUTE:** chặn route/replica khai trong body; chuyển `slides.search` sang `slides.query`; ghim `Mcp-Replica` vào header.
  - **ADMIT:** chặn `get_frame` không có lease sống, lệnh chứa chỉ thị bị chèn, server/Agent Card không được xác thực, peer chưa kiểm chứng, payload phình to, và lệnh lặp lại y hệt một lệnh đã lỗi.
  - **AUTHORIZE:** target phải đúng `ctx.act`; `aud` phải khớp server được gọi; lệnh ghi cần scope `wiki.write:<server>`, có `If-Match`, và `Idempotency-Key` chưa từng dùng.
  - **BUDGET:** chuyển mask "nút tự phạt" sang mask rẻ; chặn discovery khi credit xuống dưới mức dự trữ.

  `decide()` không bao giờ ném exception: lỗi nội bộ thì từ chối (fail closed).
- **PROSECUTE — `eval/prosecute.py`:** cài đủ 16 hook, mỗi family chọn một cáo buộc theo thứ tự ưu tiên, không cáo buộc trùng sự kiện gốc. Trên 40 fixture có nhãn đạt precision 1.000, recall 1.000, 0 cáo buộc sai.
- **ATTACK — `deck/deck.json`:** 4 lá atk_03/04/05/09 đổi `defense_event` thành `gateway.denied` (theo khuyến nghị trong `deck/README.md`), để cả trọng tài lẫn spar đều xác nhận được `enforcement_failure`. `validate` đạt 0 FAIL.

## Kết quả đấu thử (`spar.py --as all`, seed 1–3)

| Bot | Kết quả |
|---|---|
| rookie | thắng 100–0 (cả 3 seed) |
| operator | thắng 100–0 (cả 3 seed) |
| adversary | thắng 72–0, 48–19, 72–13 |

Máu bị mất khi đấu adversary đều đến từ `fabricated_citation`. Lỗi này do harness của spar tự chèn một anchor ngẫu nhiên vào câu trả lời (xác suất 35%), không phải do gateway cho lọt lệnh nào.

*Có dùng AI:* Claude Code (Claude Opus 5.5) hỗ trợ đọc kit, viết detector/gateway và chạy kiểm thử. Tôi đã review và giải thích được mọi thay đổi.
