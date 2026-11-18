# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay: verdict của judge lưu sẵn trong CSV, không cần key). Lớp dương = **FAIL**, vì nhiệm vụ của judge là *tìm* reply lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng** (chỉ cho tone, không chặn release một mình) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại** |

Ma trận nhầm lẫn (FAIL là lớp dương):

| | Người FAIL | Người PASS |
|---|---|---|
| **tone_ok**: judge FAIL | TP 24 | FP 4 |
| **tone_ok**: judge PASS | FN 6 | TN 66 |
| **helpful**: judge FAIL | TP 9 | FP 0 |
| **helpful**: judge PASS | **FN 21** | TN 70 |

Rogan-Gladen: tone quan sát 0.28 → hiệu chỉnh 0.30. Helpful quan sát 0.09 → hiệu chỉnh 0.30, đúng bằng tỉ lệ lỗi theo người (30/100). Hiệu chỉnh này chỉ sửa được **tỉ lệ tổng**, không cho biết reply *nào* lỗi, nên không cứu được judge helpful khi dùng làm gate theo từng item.

## Audit thủ công các case bất đồng

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. **Rubric:** thêm luật xưng hô: "LogiX" / "anh/chị", cấm "em/bạn" và tiểu từ "nha/nhé", kèm 2 ví dụ FAIL. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ ... rồi nha." | PASS | FAIL | Người | Cùng lỗi xưng hô; judge coi "thân thiện" là tốt. Cùng sửa như #1. |
| 3 | tone H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ thấy "Dạ, vui lòng" nên cho qua, bỏ sót câu ra lệnh. **Rubric:** chấm cả câu, liệt kê cụm cấm ("không cần nhắn thêm", "vui lòng chờ" mà không có mốc thời gian). |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". **Rubric:** ghi rõ "xin lỗi không bắt buộc khi kết quả là hoàn tiền; ngắn và đủ ý = PASS". |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ ..." | FAIL | PASS | Người | Style guide CS LogiX cho phép dùng "refund". **Rubric:** thêm whitelist thuật ngữ được phép (refund, ship, voucher). |
| 6 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn ..." | FAIL | PASS | **Judge** | Nhãn người sai (người gán nhãn đọc nhầm ticket). **Hành động:** sửa nhãn trong bộ nhãn người, không sửa rubric. Bất đồng không có nghĩa judge luôn sai. |
| 7 | tone H-063 "... đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải tone: chuyển sang grader code (reply chỉ được nêu số ledger, xem FM-08), không bắt judge tone gánh. |
| 8 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | **Judge không nhìn thấy ledger**, nên không thể biết số tiền sai. Cả 18/18 case "sai tiền" đều bị judge cho PASS. Không sửa được bằng rubric: chuyển sang `reply_amount_matches_ledger` (code). |
| 9 | helpful HL-016 / HL-028 / HL-043 … (xin lỗi dài 2 lần + số tiền sai) | PASS | FAIL | Người | Judge thiên vị câu dài, nhiều lời xin lỗi (verbosity bias): xin lỗi càng nhiều càng được cho "helpful", dù số tiền sai. **Rubric:** "helpful = đúng kết quả + bước tiếp theo rõ ràng; độ dài và lời xin lỗi không cộng điểm". |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Sai xưng hô và không nói kết quả cụ thể (bao nhiêu tiền, khi nào về). **Rubric:** reply `resolved` phải có số tiền và thời gian tiền về. |

## Kết luận

- **tone_ok: dùng được.** κ = 0.757, P = 0.857, R = 0.8 đều trên sàn. 6 FN chủ yếu là lỗi xưng hô / giọng ra lệnh, sửa được bằng rubric (#1–#3). Dù vậy, tone chỉ là tiêu chí phụ: không đưa vào gate chặn release, chỉ theo dõi.
- **helpful: loại, không được dùng làm gate.** Recall = 0.30: judge bỏ sót 21/30 reply mà người đánh FAIL, trong đó **18/18 case "sai tiền" bị cho PASS** (FN). κ = 0.375 < 0.6. Precision = 1.0 trông đẹp nhưng vô nghĩa: judge chỉ bắt được các lỗi dễ (giọng cụt, lạc đề, không hỏi mã đơn) và để lọt đúng loại lỗi đắt nhất. Nếu dùng làm gate, một PR làm reply nói sai tiền vẫn xanh. Đây là lý do tiền luôn chấm bằng code: `reply_amount_matches_ledger` so reply với ledger, thứ judge không có trong input.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Rubric sau khi sửa phải được chấm lại trên một tập nhãn người **mới** (held-out) trước khi tin κ mới. Một số nhãn người cũng sai (#6), nên cần 2 người gán nhãn và đo κ giữa người với người.
