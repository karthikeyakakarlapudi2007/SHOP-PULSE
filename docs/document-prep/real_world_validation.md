> **Simulated camera captures** of the repository's invoice layouts (not real photographs). See `tests/real_world_validation.py` for the camera model; run it with `--photos` on real photos.

Cases: 81 · line items: 416 · fully correct lines (name+qty+rate+amount): **15 → 248**

| Field | Correct today | Correct with preparation |
|---|---|---|
| name | 38 | 277 |
| quantity | 21 | 255 |
| rate | 22 | 259 |
| amount | 27 | 267 |

| Condition | Cases | Lines | Correct today | Correct with preparation | Critical-token recall today → prepared |
|---|---|---|---|---|---|
| sideways | 10 | 51 | 0 | 44 | 0.000 → 0.943 |
| upside_down | 10 | 51 | 0 | 46 | 0.000 → 0.956 |
| low_light | 10 | 51 | 0 | 32 | 0.000 → 0.841 |
| shadow | 10 | 51 | 2 | 43 | 0.424 → 0.939 |
| perspective | 10 | 51 | 3 | 32 | 0.276 → 0.836 |
| tilted | 10 | 51 | 10 | 37 | 0.100 → 0.948 |
| blurry | 10 | 51 | 0 | 6 | 0.000 → 0.307 |
| small_text | 10 | 51 | 0 | 0 | 0.000 → 0.256 |
| multi_page (page 2 sideways) | 1 | 8 | 0 | 8 | 0.000 → 1.000 |

| Case | Rotation applied | Quality | Version | Lines correct today → prepared | Critical tokens today → prepared |
|---|---|---|---|---|---|
| TC02_bordered_image__sideways | 270 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/5 → 4/5 | 0.00 → 1.00 |
| TC02_bordered_image__upside_down | 180 | GOOD -> POOR | enhanced | 0/5 → 5/5 | 0.00 → 1.00 |
| TC02_bordered_image__low_light | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/5 → 4/5 | 0.00 → 1.00 |
| TC02_bordered_image__shadow | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/5 → 5/5 | 0.00 → 1.00 |
| TC02_bordered_image__perspective | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/5 → 5/5 | 0.00 → 1.00 |
| TC02_bordered_image__tilted | 0 | GOOD -> EXCELLENT | enhanced | 0/5 → 5/5 | 0.00 → 1.00 |
| TC02_bordered_image__blurry | 0 | UNREADABLE -> POOR | enhanced | 0/5 → 0/5 | 0.00 → 0.00 |
| TC02_bordered_image__small_text | 0 | POOR -> POOR | enhanced | 0/5 → 0/5 | 0.00 → 0.53 |
| TC13_sri_balaji_13items__sideways | 270 | GOOD -> POOR | enhanced | 0/13 → 8/13 | 0.00 → 0.64 |
| TC13_sri_balaji_13items__upside_down | 180 | GOOD -> EXCELLENT | enhanced | 0/13 → 8/13 | 0.00 → 0.64 |
| TC13_sri_balaji_13items__low_light | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/13 → 0/13 | 0.00 → 0.62 |
| TC13_sri_balaji_13items__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/13 → 8/13 | 0.13 → 0.64 |
| TC13_sri_balaji_13items__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/13 → 0/13 | 0.18 → 0.36 |
| TC13_sri_balaji_13items__tilted | 0 | GOOD -> POOR | enhanced | 0/13 → 0/13 | 0.00 → 0.56 |
| TC13_sri_balaji_13items__blurry | 0 | NEEDS_ENHANCEMENT -> GOOD | enhanced | 0/13 → 0/13 | 0.00 → 0.21 |
| TC13_sri_balaji_13items__small_text | 0 | POOR -> GOOD | enhanced | 0/13 → 0/13 | 0.00 → 0.38 |
| TC15_decimal_quantities__sideways | 270 | GOOD -> POOR | enhanced | 0/3 → 3/3 | 0.00 → 0.92 |
| TC15_decimal_quantities__upside_down | 180 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 0.92 |
| TC15_decimal_quantities__low_light | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 0.92 |
| TC15_decimal_quantities__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 0/3 | 0.50 → 0.75 |
| TC15_decimal_quantities__perspective | 0 | NEEDS_ENHANCEMENT -> POOR | binarized | 0/3 → 1/3 | 0.00 → 0.67 |
| TC15_decimal_quantities__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 0.92 |
| TC15_decimal_quantities__blurry | 0 | UNREADABLE -> POOR | enhanced | 0/3 → 0/3 | 0.00 → 0.33 |
| TC15_decimal_quantities__small_text | 0 | POOR -> NEEDS_ENHANCEMENT | binarized | 0/3 → 0/3 | 0.00 → 0.08 |
| TC16_borderless_table__sideways | 270 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC16_borderless_table__upside_down | 180 | NEEDS_ENHANCEMENT -> EXCELLENT | binarized | 0/4 → 4/4 | 0.00 → 1.00 |
| TC16_borderless_table__low_light | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | binarized | 0/4 → 4/4 | 0.00 → 1.00 |
| TC16_borderless_table__shadow | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/4 → 4/4 | 0.25 → 1.00 |
| TC16_borderless_table__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC16_borderless_table__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC16_borderless_table__blurry | 0 | UNREADABLE -> POOR | corrected | 0/4 → 0/4 | 0.00 → 0.00 |
| TC16_borderless_table__small_text | 0 | POOR -> NEEDS_ENHANCEMENT | corrected | 0/4 → 0/4 | 0.00 → 0.00 |
| TC17_multi_tier_gst__sideways | 270 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 3/4 | 0.00 → 0.88 |
| TC17_multi_tier_gst__upside_down | 180 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC17_multi_tier_gst__low_light | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/4 → 3/4 | 0.00 → 0.88 |
| TC17_multi_tier_gst__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC17_multi_tier_gst__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 4/4 | 0.00 → 1.00 |
| TC17_multi_tier_gst__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/4 → 3/4 | 0.00 → 1.00 |
| TC17_multi_tier_gst__blurry | 0 | POOR -> NEEDS_ENHANCEMENT | enhanced | 0/4 → 0/4 | 0.00 → 0.25 |
| TC17_multi_tier_gst__small_text | 0 | POOR -> POOR | corrected | 0/4 → 0/4 | 0.00 → 0.00 |
| TC20_faded_thermal_receipt__sideways | 270 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC20_faded_thermal_receipt__upside_down | 180 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC20_faded_thermal_receipt__low_light | 0 | NEEDS_ENHANCEMENT -> NEEDS_ENHANCEMENT | corrected | 0/3 → 0/3 | 0.00 → 0.00 |
| TC20_faded_thermal_receipt__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | corrected | 2/3 → 3/3 | 1.00 → 1.00 |
| TC20_faded_thermal_receipt__perspective | 0 | POOR -> EXCELLENT | enhanced | 3/3 → 3/3 | 1.00 → 1.00 |
| TC20_faded_thermal_receipt__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC20_faded_thermal_receipt__blurry | 0 | UNREADABLE -> NEEDS_ENHANCEMENT | corrected | 0/3 → 0/3 | 0.00 → 0.00 |
| TC20_faded_thermal_receipt__small_text | 0 | UNREADABLE -> POOR | corrected | 0/3 → 0/3 | 0.00 → 0.00 |
| TC25_split_column_headers__sideways | 270 | GOOD -> POOR | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC25_split_column_headers__upside_down | 180 | NEEDS_ENHANCEMENT -> EXCELLENT | binarized | 0/3 → 3/3 | 0.00 → 1.00 |
| TC25_split_column_headers__low_light | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC25_split_column_headers__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 1.00 → 1.00 |
| TC25_split_column_headers__perspective | 0 | NEEDS_ENHANCEMENT -> POOR | binarized | 0/3 → 2/3 | 0.00 → 1.00 |
| TC25_split_column_headers__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC25_split_column_headers__blurry | 0 | UNREADABLE -> NEEDS_ENHANCEMENT | enhanced | 0/3 → 1/3 | 0.00 → 0.33 |
| TC25_split_column_headers__small_text | 0 | POOR -> POOR | corrected | 0/3 → 0/3 | 0.00 → 0.00 |
| TC26_promotional_scheme__sideways | 270 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC26_promotional_scheme__upside_down | 180 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC26_promotional_scheme__low_light | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC26_promotional_scheme__shadow | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/3 → 3/3 | 0.83 → 1.00 |
| TC26_promotional_scheme__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 1.00 → 1.00 |
| TC26_promotional_scheme__tilted | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC26_promotional_scheme__blurry | 0 | UNREADABLE -> POOR | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC26_promotional_scheme__small_text | 0 | POOR -> POOR | binarized | 0/3 → 0/3 | 0.00 → 1.00 |
| TC31_high_density_compact__sideways | 270 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/10 → 10/10 | 0.00 → 1.00 |
| TC31_high_density_compact__upside_down | 180 | GOOD -> POOR | enhanced | 0/10 → 10/10 | 0.00 → 1.00 |
| TC31_high_density_compact__low_light | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/10 → 9/10 | 0.00 → 1.00 |
| TC31_high_density_compact__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/10 → 10/10 | 0.20 → 1.00 |
| TC31_high_density_compact__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/10 → 10/10 | 0.25 → 1.00 |
| TC31_high_density_compact__tilted | 0 | GOOD -> POOR | original | 10/10 → 10/10 | 1.00 → 1.00 |
| TC31_high_density_compact__blurry | 0 | NEEDS_ENHANCEMENT -> POOR | enhanced | 0/10 → 2/10 | 0.00 → 0.95 |
| TC31_high_density_compact__small_text | 0 | POOR -> GOOD | corrected | 0/10 → 0/10 | 0.00 → 0.00 |
| TC32_alternate_column_order__sideways | 270 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC32_alternate_column_order__upside_down | 180 | GOOD -> POOR | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC32_alternate_column_order__low_light | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.00 → 1.00 |
| TC32_alternate_column_order__shadow | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | enhanced | 0/3 → 3/3 | 0.33 → 1.00 |
| TC32_alternate_column_order__perspective | 0 | NEEDS_ENHANCEMENT -> EXCELLENT | original | 0/3 → 0/3 | 0.33 → 0.33 |
| TC32_alternate_column_order__tilted | 0 | GOOD -> POOR | corrected | 0/3 → 3/3 | 0.00 → 1.00 |
| TC32_alternate_column_order__blurry | 0 | UNREADABLE -> POOR | corrected | 0/3 → 0/3 | 0.00 → 0.00 |
| TC32_alternate_column_order__small_text | 0 | POOR -> POOR | binarized | 0/3 → 0/3 | 0.00 → 0.56 |
| multi_page__TC24+TC29 | 0, 270 | NEEDS_ENHANCEMENT -> EXCELLENT, GOOD -> POOR | enhanced, enhanced | 0/8 → 8/8 | 0.00 → 1.00 |
