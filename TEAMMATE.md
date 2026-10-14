# BÁO CÁO PHÂN CÔNG NHÓM & KẾT QUẢ TRIỂN KHAI
## Day 26 · Colosseum Agent Arena Kit (MCP/A2A Infrastructure & Agentic Routing)

---

### 1. THÔNG TIN THÀNH VIÊN & NHÓM (TEAM INFORMATION)

- **Tên đội (Team Name):** `2A202602391-LeVanSang`
- **Repository:** [Day26-Colosseum-Agent-Arena-Kit](https://github.com/sanh1ie77e/Day26-Colosseum-Agent-Arena-Kit)
- **Nhánh làm việc chính:** `main` (tích hợp) / `person2-prosecutor` (nhánh chuyên trách Người 2)
- **Bundle nộp bài:** `submissions/2A202602391-LeVanSang.bundle` (80,934 bytes, sha256 sealed)

#### Danh sách thành viên:

| STT | Họ và tên | Mã sinh viên | Email | GitHub | Vai trò trong nhóm | Vị trí chuyên trách |
|---|---|---|---|---|---|---|
| 1 | **Lê Văn Sang** | `2A202602391` | `lesang08092005@gmail.com` | `sanh1ie77e` | **Nhóm trưởng** (Team Leader) | **Người 2** — PROSECUTOR + ATTACKER |
| 2 | **Nguyễn Bá Chính** | `2A202602654` | `chinhlhiep@gmail.com` | `Bancainh` | Thành viên (Member) | **Người 1** — DEFENDER |

---

### 2. PHÂN CÔNG NHIỆM VỤ CHI TIẾT (TASK BREAKDOWN)

| Người | Vai trò | Phần phụ trách | File chính | Mục tiêu & Kết quả đạt được |
|---|---|---|---|---|
| **Người 1**<br>*(Nguyễn Bá Chính)* | **DEFENDER** | Phòng thủ agent | `agent/gateway.py`<br>`agent/strategy.py`<br>`agent/prompt.md`<br>`agent/telemetry.py`<br>`agent/runtime.py` | - Route đúng replica/tool, chặn call sai.<br>- Kiểm tra quyền (authority), budget, lease, write headers.<br>- Giảm thiểu lãng phí (waste).<br>- **Kết quả:** Đạt chuẩn toàn bộ bài test tại `tests/test_defender_gateway.py`. |
| **Người 2**<br>*(Lê Văn Sang)* | **PROSECUTOR +<br>ATTACKER** | Bắt lỗi đối phương +<br>Thiết kế attack | `eval/prosecute.py`<br>`agent/guardrails.py`<br>`deck/deck.json`<br>`deck/lineup.json` | - Hoàn thiện 16 detector còn thiếu, đạt F1 = 1.000 (34/34 fixtures verified, 0 penalty).<br>- Rào chắn chống prompt injection, rò rỉ privacy, hallucination và xác thực số học.<br>- Tối ưu deck 14 lá (10 attack + 4 blank, 9 classes) và lineup hợp lệ.<br>- **Kết quả:** Pass 100% test `test_prosecute.py`, `test_person2_safety.py`, `test_validate_deck.py`. |

---

### 3. TỔNG HỢP KẾT QUẢ ĐO KIỂM & NGHIỆM THU

1. **Tổng thể Test Suite:**
   - Chạy toàn bộ các bộ test chính (`test_person2_safety.py`, `test_person2_review.py`, `test_defender_gateway.py`, `test_prosecute.py`):
     ```text
     ============================= 99 passed in 0.56s ==============================
     ```
   - **Tất cả 99/99 bài kiểm tra đều ĐẠT (PASS 100%)**.

2. **Bộ công tố (`eval/prosecute.py` - Người 2):**
   - **Precision:** `1.000` (Không cáo buộc sai)
   - **Recall:** `1.000` (Bắt trọn 100% tất cả lỗi vi phạm)
   - **F1 Score:** `1.000`
   - **False Claim Rate:** `0.000` (34/34 verified claims, 0 penalty).

3. **Rào chắn an toàn (`agent/guardrails.py` - Người 2):**
   - Vượt qua toàn bộ 24 test an toàn về prompt injection đa ngôn ngữ, che giấu dữ liệu học viên (PII redaction) và xác thực phương trình số học an toàn.

4. **Bộ bài tấn công (`deck/deck.json` & `deck/lineup.json` - Người 2):**
   - 14 lá bài hợp lệ (10 attack + 4 blank), 9 duel classes, chuẩn hóa `defense_event: "gateway.denied"`.
   - Kiểm tra trực tiếp với ngữ liệu thực tế `kit/world/df8c55dabb35`: **PASS 100% (0 failing checks)**.

5. **Bộ phòng thủ Gateway (`agent/gateway.py` - Người 1):**
   - Kiểm soát chặt chẽ 4 tầng: ROUTE, ADMIT, AUTHORIZE, BUDGET.
   - Chặn đứng các đòn tấn công giả mạo token, lease hết hạn, header write thiếu hoặc không hợp lệ.

---

### 4. LỆNH KIỂM TRA & ĐÓNG GÓI NỘP BÀI (COMMANDS)

Chạy trực tiếp từ thư mục gốc dự án:

```powershell
# 1. Đo kiểm điểm công tố (Người 2)
python -m eval.prosecute
python -m pytest tests/test_prosecute.py -v

# 2. Kiểm tra bộ guardrails & an toàn (Người 2)
python -m pytest tests/test_person2_safety.py -v

# 3. Kiểm tra Gateway phòng thủ (Người 1)
python -m pytest tests/test_defender_gateway.py -v

# 4. Kiểm tra bộ bài với ngữ liệu thật (Người 2)
python validate_deck.py deck/deck.json deck/lineup.json --world kit/world/df8c55dabb35

# 5. Lệnh đóng gói nộp bài chính thức
python -m kit.submit --team 2A202602391-LeVanSang
```
*(Bundle xuất ra thành công: `submissions/2A202602391-LeVanSang.bundle`).*
