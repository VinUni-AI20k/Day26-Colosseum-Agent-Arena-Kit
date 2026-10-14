# BÁO CÁO PHÂN CÔNG NHÓM & KẾT QUẢ TRIỂN KHAI
## Day 26 · Colosseum Agent Arena Kit (MCP/A2A Infrastructure & Agentic Routing)

---

### 1. THÔNG TIN THÀNH VIÊN & NHÓM (TEAM INFORMATION)

- **Tên đội (Team Name):** `2A202602391-LeVanSang`
- **Nhóm trưởng (Team Leader):** Lê Văn Sang
  - **Mã sinh viên:** `2A202602391`
  - **Email:** `lesang08092005@gmail.com`
  - **GitHub:** `sanh1ie77e`
  - **Vai trò trong Lab:** Nhóm trưởng / Phụ trách chính Person 2 (Công tố viên, Soạn bài tấn công, Rào chắn an toàn)
- **Repository:** [Day26-Colosseum-Agent-Arena-Kit](https://github.com/sanh1ie77e/Day26-Colosseum-Agent-Arena-Kit)
- **Nhánh triển khai:** `person2-prosecutor` (đã tạo Pull Request #1 và merge sạch sẽ vào `main`)
- **Bundle nộp bài:** `submissions/2A202602391-LeVanSang.bundle` (72,804 bytes, sha256 sealed)

---

### 2. PHÂN CHIA VAI TRÒ & NHIỆM VỤ (WORK BREAKDOWN)

| Thành viên | Phụ trách | File sở hữu | Trạng thái |
|---|---|---|---|
| **Lê Văn Sang** *(Nhóm trưởng)* | **Person 2**:<br>- Công tố viên (`Prosecutor`)<br>- Tấn công (`Attacker`)<br>- Rào chắn an toàn (`Guardrails`) | `eval/prosecute.py`<br>`agent/guardrails.py`<br>`deck/deck.json`<br>`deck/lineup.json` | **HOÀN THÀNH 100%**<br>(F1 = 1.000, 41/41 tests passed, deck hợp lệ) |
| **Thành viên phối hợp** | **Person 1**:<br>- Bộ định tuyến bảo vệ (`Gateway`)<br>- Chiến lược gọi tool (`Strategy`) | `agent/gateway.py`<br>`agent/strategy.py`<br>`agent/prompt.md` | Đang tích hợp |

---

### 3. CHI TIẾT KẾT QUẢ ĐÃ ĐẠT ĐƯỢC (DELIVERABLES)

#### 3.1. Bộ công tố bắt lỗi đối thủ (`eval/prosecute.py`)
- Cài đặt đầy đủ **16 hook detectors** theo đúng chuẩn `CONTRACTS.md` và `rubric` trọng số của giải đấu:
  - **Family A (Hạ tầng & Giao thức - Trọng số cao):** `stale_read` (w=8), `write_violation` (w=8), `protocol_misuse` (w=6). Đảm bảo không bắt nhầm các lệnh đã bị gateway `deny`.
  - **Family B (Căn cứ & Tính trung thực):** `wrong_answer` (w=8), `fabricated_citation` (w=8), `hallucination` (w=7), `ungrounded` (w=5), `unsupported_precision` (w=4).
  - **Family C (Bảo mật & Quyền hạn):** `authority_exceeded` (w=10), `guardrail_breach` (w=8), `privacy_leak` (w=8), `unflagged_conflict` (w=6).
  - **Family D (Chi phí & Tài nguyên):** `overreach` (w=5), `incoherent` (w=4), `non_responsive` (w=4), `wasteful` (w=3).
- Thực thi nghiêm ngặt ngân sách công tố qua `ProsecutionBudget`: tối đa 4 cáo buộc/hiệp, tối đa 1 cáo buộc/family.
- **Điểm số kiểm tra thực tế trên 40 labelled fixtures (`python -m eval.prosecute`):**
  - **Precision:** `1.000` (Tuyệt đối, không cáo buộc sai)
  - **Recall:** `1.000` (Bắt trọn 100% tất cả lỗi vi phạm)
  - **F1 Score:** `1.000`
  - **False Claim Rate:** `0.000` (34/34 verified claims, 0 penalty)
  - **Unit test suite:** `pytest tests/test_prosecute.py` đạt **41/41 PASSED**.

#### 3.2. Rào chắn bảo vệ câu trả lời (`agent/guardrails.py`)
- **Phát hiện Prompt Injection (`scan_for_injected_instructions`):** Nhận diện các lệnh chèn độc hại trong retrieved text cả tiếng Anh và tiếng Việt (`ignore previous instructions`, `system override`, `bỏ qua mọi hướng dẫn`, ...).
- **Che giấu dữ liệu nhạy cảm (`redact`):** Nhận diện và che giấu email, token/API key, mã học viên (`sv-xxxx`), điểm số đánh giá riêng tư mà vẫn bảo toàn nội dung bài học.
- **Xác thực số học (`verify_arithmetic`):** Kiểm tra tính toán phương trình số học an toàn không dùng `eval()`, đối chiếu số liệu với bằng chứng thực tế, ngăn chặn bịa số thập phân không có căn cứ.

#### 3.3. Bộ bài tấn công & Đội hình ra sân (`deck/deck.json` & `deck/lineup.json`)
- Đầy đủ **14 lá bài**: 10 lá tấn công (`atk_01` – `atk_10`) + 4 lá trắng (`blk_01` – `blk_04`).
- Cân bằng các tầng tấn công: **4 lá MCP-layer** ($\ge 3$), **4 lá A2A-layer** ($\ge 3$), **2 lá Gateway-layer** ($\ge 2$).
- Phủ rộng **9 lớp tấn công** khác nhau ($\ge 6$ theo luật).
- Chuẩn hóa toàn bộ `defense_event` thành `"gateway.denied"`.
- `lineup.json` chứa đúng 10 lá bài tấn công theo thứ tự khóa tối ưu.
- Đã kiểm tra qua `validate_deck.py` với ngữ liệu thực tế `df8c55dabb35`: **PASS 100% (0 failing checks)**.

---

### 4. HƯỚNG DẪN KIỂM TRA & NGHIỆM THU (VERIFICATION COMMANDS)

Chạy các lệnh sau tại thư mục gốc của repo:

```powershell
# 1. Kiểm tra bộ công tố
python -m eval.prosecute
python -m pytest tests/test_prosecute.py -v

# 2. Kiểm tra guardrails an toàn
python -m agent.guardrails

# 3. Kiểm tra tính hợp lệ của bộ bài tấn công
python validate_deck.py deck/deck.json deck/lineup.json --world kit/world/df8c55dabb35
python -m pytest tests/test_validate_deck.py -v

# 4. Đóng gói nộp bài chính thức
python -m kit.submit --team 2A202602391-LeVanSang
```
*(File nộp bài sinh ra tại `submissions/2A202602391-LeVanSang.bundle`).*
