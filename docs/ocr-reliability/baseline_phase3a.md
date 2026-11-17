# Extraction baseline (repository datasets — NOT real-world evidence)

## fixtures

Cases 32 · line items 160 · found 155 · fully correct 145 · partially correct 10 · errors 1

| Field | Evaluated | Correct | Invented |
|---|---|---|---|
| product_name | 160 | 145 | 0 |
| quantity | 160 | 155 | 0 |
| unit | 118 | 109 | 0 |
| purchase_price | 157 | 152 | 3 |
| mrp | 100 | 95 | 0 |
| printed_amount | 160 | 155 | 0 |

Wrong qty/rate/amount on 0 found lines: flagged 0, **silent 0**. Extra (non-invoice) lines 0, flagged 0.

Decimal corruption: 0

| Header field | correct | correct_empty | missed | partial |
|---|---|---|---|---|
| supplier_name | 22 | 1 | 0 | 9 |
| invoice_number | 29 | 1 | 2 | 0 |
| invoice_date | 30 | 1 | 1 | 0 |

## synthetic

Cases 17 · line items 121 · found 114 · fully correct 104 · partially correct 10 · errors 0

| Field | Evaluated | Correct | Invented |
|---|---|---|---|
| product_name | 121 | 107 | 0 |
| quantity | 121 | 112 | 0 |
| unit | 121 | 110 | 0 |
| purchase_price | 121 | 112 | 0 |
| mrp | 121 | 114 | 0 |
| printed_amount | 121 | 114 | 0 |

Wrong qty/rate/amount on 4 found lines: flagged 4, **silent 0**. Extra (non-invoice) lines 0, flagged 0.

Decimal corruption: 0

| Header field | correct | missed | wrong |
|---|---|---|---|
| supplier_name | 14 | 0 | 3 |
| invoice_number | 15 | 2 | 0 |
| invoice_date | 15 | 2 | 0 |

## simulated

Cases 81 · line items 416 · found 317 · fully correct 250 · partially correct 62 · errors 0

| Field | Evaluated | Correct | Invented |
|---|---|---|---|
| product_name | 416 | 267 | 0 |
| quantity | 416 | 290 | 0 |
| unit | 204 | 109 | 0 |
| purchase_price | 416 | 287 | 0 |
| mrp | 196 | 120 | 0 |
| printed_amount | 416 | 303 | 0 |

Wrong qty/rate/amount on 36 found lines: flagged 24, **silent 12**. Extra (non-invoice) lines 22, flagged 14.

Decimal corruption: 14
- TC13_sri_balaji_13items__low_light: CHANA 50 KG purchase_price 2760.0 -> 276000.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__low_light: CHANA 50 KG mrp 3200.0 -> 320000.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__perspective: HELLO ORGANIC CHANA DAL 1 KG mrp 160.0 -> 16000.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__perspective: MASOOR DAL 50 KG purchase_price 4825.0 -> 482500.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__perspective: MASOOR DAL 50 KG mrp 5600.0 -> 560000.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__tilted: RAJAMM mrp 58.0 -> 5800.0 (decimal shifted by 10^2)
- TC13_sri_balaji_13items__blurry: CHANA 50 KG printed_amount 2760.0 -> 2.76 (decimal shifted by 10^3)
- TC15_decimal_quantities__perspective: Royal Cashew Nuts W320 printed_amount 660.0 -> 66000.0 (decimal shifted by 10^2)
- TC15_decimal_quantities__perspective: Tata Sampann Moong Dal printed_amount 350.0 -> 35000.0 (decimal shifted by 10^2)
- TC15_decimal_quantities__blurry: India Gate Basmati Rice purchase_price 160.0 -> 0.16 (decimal shifted by 10^3)
- TC15_decimal_quantities__small_text: Tata Sampann Moong Dal purchase_price 140.0 -> 14000.0 (decimal shifted by 10^2)
- TC17_multi_tier_gst__sideways: Aashirvaad Atta 5kg purchase_price 245.0 -> 24500.0 (decimal shifted by 10^2)
- TC17_multi_tier_gst__low_light: Aashirvaad Atta 5kg purchase_price 245.0 -> 24500.0 (decimal shifted by 10^2)
- TC17_multi_tier_gst__tilted: Aashirvaad Atta 5kg purchase_price 245.0 -> 24500.0 (decimal shifted by 10^2)

| Header field | correct | missed | not_recorded | partial | wrong |
|---|---|---|---|---|---|
| supplier_name | 52 | 10 | 1 | 7 | 11 |
| invoice_number | 57 | 23 | 1 | 0 | 0 |
| invoice_date | 62 | 14 | 1 | 0 | 4 |
