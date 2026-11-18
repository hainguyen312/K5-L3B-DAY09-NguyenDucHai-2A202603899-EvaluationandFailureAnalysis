# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Output thật

```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
-- trace (step, kind, payload)
   1 handoff            {"contract_version": "handoff.v1", "request_id": "REQ-C-014", "claim_id": "C-014", ...
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-515", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 150000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03", "DMG-04"], "parts": {"SHIP-LATE-03": 30000, "DMG-04": 150000}}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
-- ledger vs label
  refund_vnd     ledger=90000    label=120000   <-- differs
  refund_count   ledger=1        label=1
  status         result=resolved label=resolved

== fixed C-014@11  lab8 grader: PASS (ok)
   1 handoff · 2 investigator · 3 quote {"amount_vnd": 150000, ...} · 4 reply "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."
  refund_vnd     ledger=120000   label=120000
```

## Case

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11` (T14), report `reports/eval_seeded_regression.json`, run ID `E-seeded_regression-20261118-5ed0`, row `E-014@11` |
| Triệu chứng | `refund_amount_correct` = False (ledger 90.000 ≠ nhãn 120.000), `reply_amount_matches_ledger` = False (reply nói 120.000đ, ledger 90.000), `proposal_amount_correct` = False (120.000 ≠ 150.000), `pass_rate` = False (`proposal_mismatch`). **Reply nghe hoàn toàn đúng** ("đã hoàn 120.000đ", đúng con số khách đáng được nhận), nhưng ledger chỉ ghi 90.000: khách bị thiếu 30.000đ. |
| Bước sai đầu tiên | **Event 5 `proposal {"amount_vnd": 120000}`**: agent lấy quote 150.000 trừ đi 30.000 đã hoàn (từ event 4), rồi gửi 120.000 cho `issue_refund`. Host tự áp trần theo đơn nên trừ 30.000 thêm lần nữa → 90.000. |
| Vì sao là bước *đầu tiên* | Event 1–2 đúng: handoff đúng claim, investigator đọc đúng O-515 (trễ 5 ngày, `damage_verified=true`). Event 3 đúng: quote 150.000 = max(ship 30.000, damage 150.000), không cộng. Event 4 là một lần đọc hợp lệ (read tool `lookup_refund_history`, không đổi state). Event 5 là bước đầu tiên làm sai luật nghiệp vụ: "truyền quote đầy đủ vào `issue_refund`, host tự trừ phần đã hoàn". |
| Failure mode | **FM-05 pre_deducted** (`docs/failure_taxonomy.md`). Triệu chứng phụ: reply báo số tự tính chứ không phải số host ghi (dạng FM-08). |
| Đối chứng | `fixed C-014@11`: không có event `refund_history` / `proposal`. Quote 150.000 đi thẳng vào host, host trả 120.000, ledger 120.000 = nhãn, reply 120.000đ khớp ledger. |
| Regression test | `tests/test_lab9_trace_case.py::test_trace_case_c014_pre_deducted_is_caught` (chạy `seeded_regression C-014@11`, assert `proposal` đứng ngay sau `refund_history`, ledger 90.000, `RefundAmountCorrect` và `ReplyAmountMatchesLedger` đều False) và `::test_trace_case_c014_fixed_passes` (cùng claim@seed trên `fixed`: ledger 120.000, cả hai grader True). Đã chạy: **fail trên variant lỗi, pass trên `fixed`**. Cả hai test có marker `student`, nên chạy trong job `eval-gate`. |
| Chưa chắc chắn | Trace không ghi kết quả gọi host (`issue_refund` không có event riêng), nên con số 90.000 là suy ra từ ledger, không thấy trực tiếp "host trừ lần hai". MockLLM tất định: không biết với LLM thật, agent có tự trừ ở mọi seed như vậy không. Một agent tự trừ nhưng vẫn báo đúng số ledger thì grader reply không bắt được; khi đó chỉ còn `refund_amount_correct` / `proposal_amount_correct`. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case này là ví dụ).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không viết chung chung kiểu "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
