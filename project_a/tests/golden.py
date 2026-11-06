"""Cases worked out by hand from the rule text, before any code ran. Each comment shows the arithmetic.
These validate the oracle, and the oracle then produces the 200+ frozen suite cases.
"""
from __future__ import annotations


def _inp(fy="2024-25", age=30, gross=0, **kw):
    base = {
        "fy": fy, "age": age, "basic_da": gross, "hra_received": 0, "other_salary": 0, "rent_paid": 0,
        "metro": False, "sec_80c": 0, "sec_80ccd1b": 0, "sec_80d_self": 0, "sec_80d_parents": 0,
        "parents_senior": False, "home_loan_interest": 0,
    }
    base.update(kw)
    return base


# (name, input, expected old tax payable, expected new tax payable)
GOLDEN = [
    # new: 10L-75k=9.25L; 20,000 + 2.25L@10%=22,500 -> 42,500; cess 1,700. old: 9.5L; 12,500 + 4.5L@20%=90,000; cess 4,100
    ("plain_10L", _inp(gross=1000000), 106600, 44200),
    # new: TI exactly 7L; tax 20,000 fully rebated. old: 7.25L; 12,500+45,000=57,500; cess 2,300
    ("new_rebate_limit", _inp(gross=775000), 59800, 0),
    # new: TI 7.1L; tax 21,000; excess 10,000 so payable 10,000; cess 400. old: 7.35L; 12,500+47,000=59,500; cess 2,380
    ("new_marginal_relief", _inp(gross=785000), 61880, 10400),
    # new: TI 7.25L; tax 22,500; excess 25,000 > tax so no relief; cess 900. old: 7.5L; 62,500; cess 2,500
    ("new_past_breakeven", _inp(gross=800000), 65000, 23400),
    # new: TI 50L; 1,40,000 at 15L + 35L@30%=10,50,000 = 11,90,000; cess 47,600. old: 50.25L; 1,12,500 + 40.25L@30%=12,07,500 -> 13,20,000 +surch 10% 1,32,000; cap at 50L: 13,12,500+25,000=13,37,500; surcharge net 17,500; cess 53,500
    ("new_50L_exact", _inp(gross=5075000), 1391000, 1237600),
    # new: TI 51L; tax 12,20,000; surch 1,22,000; ceiling 11,90,000+1,00,000=12,90,000; cess 51,600
    # old: 51.25L; 1,12,500+41.25L@30%=12,37,500 -> 13,50,000; surch 1,35,000; ceiling 13,12,500+1,25,000=14,37,500; 14,85,000 capped to 14,37,500; cess 57,500
    ("surcharge_relief_50L", _inp(gross=5175000), 1495000, 1341600),
    # old: TI 1Cr; 1,12,500+90L@30%=28,12,500; 10% 2,81,250 -> 30,93,750; cess 1,23,750
    # new: TI 1,00,25,000-... gross 1,00,50,000-75k=99,75,000; 1,40,000+84.75L@30%=25,42,500 -> 26,82,500; 10% -> 29,50,750; cess 1,18,030
    ("old_1Cr_exact", _inp(gross=10050000), 3217500, 3068780),
    # FY25 new: TI 12L; tax 60,000 fully rebated. old: 12.25L; 1,12,500+2.25L@30%=67,500 -> 1,80,000; cess 7,200
    ("fy25_rebate_limit", _inp(fy="2025-26", gross=1275000), 187200, 0),
    # FY25 new: TI 12.1L; tax 61,500; payable capped at excess 10,000; cess 400. old: 12.35L; 1,83,000; cess 7,320
    ("fy25_marginal_relief", _inp(fy="2025-26", gross=1285000), 190320, 10400),
    # FY25 new: TI 13L; tax 75,000; excess 1L > tax so no relief; cess 3,000. old: 13.25L; 2,10,000; cess 8,400
    ("fy25_past_breakeven", _inp(fy="2025-26", gross=1375000), 218400, 78000),
    # HRA least of 3L, 2.4L-60k=1.8L, 3L = 1.8L. old: 10L-1.8L-50k-1.5L=6.2L; 12,500+24,000=36,500; cess 1,460
    (
        "hra_rent_branch",
        _inp(age=35, basic_da=600000, hra_received=300000, other_salary=100000, rent_paid=240000, metro=True, sec_80c=150000),
        37960,
        44200,
    ),
    # old TI exactly 5L, age 30: 12,500 fully rebated. new: 4.75L; 8,750 rebated
    ("old_rebate_limit", _inp(gross=550000), 0, 0),
    # old TI 5,00,010: 12,502, no rebate, cess 500.08 -> 13,002.08 -> 13,000. new: 4,75,010; 8,750.5 rebated
    ("old_cliff_288B", _inp(gross=550010), 13000, 0),
    # old age 65 TI 5L: 3-5L@5%=10,000 rebated
    ("senior_rebate", _inp(age=65, gross=550000), 0, 0),
    # old age 80 TI 10L: 5L@20%=1,00,000; cess 4,000. new: 10.25... gross 10.5L-75k=9.75L; 20,000+27,500=47,500; cess 1,900
    ("super_senior_10L", _inp(age=80, gross=1050000), 104000, 49400),
    # 288A: new TI 7,00,004 rounds down to 7L -> rebated. old: 7,25,004 -> 7,25,000; 57,500+cess 2,300
    ("round_288A_down", _inp(gross=775004), 59800, 0),
    # 288A: new TI 7,00,005 rounds up to 7,00,010; tax 20,001; payable 10; cess 0.40 -> 10.40 -> 10
    # old: 7,25,005 -> 7,25,010; 57,502; cess 2,300.08 -> 59,802.08 -> 59,800
    ("round_288A_up", _inp(gross=775005), 59800, 10),
    # old: TI 5.01Cr (gross 5,01,50,000): 1,48,42,500; 37% -> 2,03,34,225; ceiling at 5Cr 1,48,12,500*1.25=1,85,15,625 +1,00,000=1,86,15,625; cess 7,44,625 -> 1,93,60,250
    # new: 5,00,75,000; 1,40,000+4,85,75,000@30%=1,45,72,500 -> 1,47,12,500; 25% -> 1,83,90,625; cess 7,35,625 -> 1,91,26,250
    ("old_5Cr_relief", _inp(gross=50150000), 19360250, 19126250),
    # old age 62: 10L after std; 80D self capped at 50k, parents non-senior capped at 25k -> 9.25L; 10,000+85,000=95,000; cess 3,800
    # new: 9.75L; 47,500; cess 1,900
    ("sec80d_caps", _inp(age=62, gross=1050000, sec_80d_self=60000, sec_80d_parents=30000), 98800, 49400),
    # old: 12L-2L cap=10L; 1,12,500; cess 4,500. new: 11.75L; 20,000+30,000+26,250=76,250; cess 3,050
    ("home_loan_cap", _inp(age=40, gross=1250000, home_loan_interest=300000), 117000, 79300),
]
