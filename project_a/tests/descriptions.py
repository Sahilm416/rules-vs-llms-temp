"""50 plain-language descriptions with gold labels, written before any parser existed.

kind: complete (answerable as written), incomplete, contradictory, out_of_scope.
`clarify` lists the question topics the system must raise:
  salary        gross annual salary missing or unclear (in-hand, CTC, no period)
  age           age or age band unknown
  hra_details   rent or HRA mentioned but rent, HRA, basic or city is missing
  deductions    a deductible item was neither stated nor ruled out
  parents_age   parents' premium above Rs 25,000 with parents' age unknown (only then does it change the cap)
  conflict      the text contradicts itself
  unsupported   income outside this calculator's scope, or not a resident
"""
from __future__ import annotations


def _gold(gross, band, **kw):
    base = {
        "gross_salary": gross, "age_band": band, "basic_da": None, "hra_received": 0, "rent_paid": 0, "metro": None,
        "sec_80c": 0, "sec_80ccd1b": 0, "sec_80d_self": 0, "sec_80d_parents": 0, "parents_senior": None, "home_loan_interest": 0,
    }
    base.update(kw)
    return base


Y, S, V = "below_60", "60_to_79", "80_plus"

DESCRIPTIONS = [
    # ---------- complete, English ----------
    ("D01", "english", "complete", "I'm 34 and my gross salary is 18 LPA. No rent, no HRA, no investments, no insurance and no home loan.", _gold(1800000, Y), []),
    ("D02", "english", "complete", "Age 29. Gross salary Rs 12,00,000 per year, of which basic plus DA is 6,00,000 and HRA is 2,40,000. I pay rent of 20,000 a month in Mumbai. 80C investments 1.5 lakh. No NPS, no health insurance, no home loan.", _gold(1200000, Y, basic_da=600000, hra_received=240000, rent_paid=240000, metro=True, sec_80c=150000), []),
    ("D03", "english", "complete", "I am a 45 year old manager with an annual gross salary of 32 lakh. I own my flat and pay 2.4 lakh interest on the home loan each year. PPF and ELSS come to 1,50,000, NPS 50,000. Health insurance for my family costs 22,000 and I pay 48,000 for my parents, who are both over 65. No rent or HRA.", _gold(3200000, Y, sec_80c=150000, sec_80ccd1b=50000, sec_80d_self=22000, sec_80d_parents=48000, parents_senior=True, home_loan_interest=240000), []),
    ("D04", "english", "complete", "Retired from government but still on a consulting salary from my employer: 68 years old, gross salary 9,60,000 a year. I have no deductions or investments of any kind.", _gold(960000, S), []),
    ("D05", "english", "complete", "I turned 82 this year. My salary as an advisor is 80,000 per month gross. No other deductions, rent, or loans.", _gold(960000, V), []),
    ("D06", "english", "complete", "Gross pay is 1.2 crore annually and I'm 50. I have no deductions at all.", _gold(12000000, Y), []),
    ("D07", "english", "complete", "Software engineer in Bengaluru, age 27. Annual gross 15,00,000: basic+DA 7,50,000, HRA 3,00,000. Rent 25k per month. 80C 80,000, nothing else: no NPS, no medical insurance, no home loan.", _gold(1500000, Y, basic_da=750000, hra_received=300000, rent_paid=300000, metro=False, sec_80c=80000), []),
    ("D08", "english", "complete", "I'm 38. Monthly gross salary is Rs 1,00,000. I live in my parents' house so I pay no rent and get no HRA. Term insurance and PF under 80C total 60k. No NPS. Mediclaim 15k for myself. No parents' policy, no home loan.", _gold(1200000, Y, sec_80c=60000, sec_80d_self=15000), []),
    ("D09", "english", "complete", "62-year-old consultant on payroll, gross 20 lakh per annum. Self health premium 55,000. Parents have passed away, so no premium for them. No 80C, no NPS, no rent, no home loan.", _gold(2000000, S, sec_80d_self=55000), []),
    ("D10", "english", "complete", "Delhi resident, 31 years old. Gross salary 22 LPA with basic and DA of 11,00,000 and HRA of 5,50,000. Rent is 6 lakh a year. 80C 1.5L, NPS 50k, no health insurance, no home loan.", _gold(2200000, Y, basic_da=1100000, hra_received=550000, rent_paid=600000, metro=True, sec_80c=150000, sec_80ccd1b=50000), []),
    # ---------- complete, terse ----------
    ("D11", "terse", "complete", "age 26 | gross 7.75L/yr | no deductions", _gold(775000, Y), []),
    ("D12", "terse", "complete", "55y, 50 lakh p.a. gross, 80c 150000, nps 50000, 80d 25000, parents 80d nil, home loan interest 200000, no rent/hra", _gold(5000000, Y, sec_80c=150000, sec_80ccd1b=50000, sec_80d_self=25000, home_loan_interest=200000), []),
    ("D13", "terse", "complete", "F, 40. Gross 2.1 Cr pa. Zero deductions.", _gold(21000000, Y), []),
    ("D14", "terse", "complete", "sal 60k pm gross, age 24, nothing to claim", _gold(720000, Y), []),
    # ---------- complete, Hinglish ----------
    ("D15", "hinglish", "complete", "Meri age 41 hai aur saal ka gross 24 lakh hai. Home loan ka interest 2.5 lakh jata hai, 80C pura 1.5 lakh hai, NPS mein 50k dalta hu. Apna mediclaim 20 hazaar hai. Rent nahi deta, HRA nahi milta, parents ka insurance nahi hai.", _gold(2400000, Y, sec_80c=150000, sec_80ccd1b=50000, sec_80d_self=20000, home_loan_interest=250000), []),
    ("D16", "hinglish", "complete", "Bhai meri umar 28 saal hai, gross salary 10 lakh per year hai. Koi investment nahi, koi insurance nahi, rent bhi nahi deta, koi loan nahi.", _gold(1000000, Y), []),
    ("D17", "hinglish", "complete", "Main 35 ka hu, Chennai mein rehta hu. Gross 14 lakh saalana, basic plus DA 7 lakh, HRA 2.8 lakh milta hai. Kiraya 15 hazaar mahina deta hu. 80C dedh lakh. NPS, insurance, home loan kuch nahi.", _gold(1400000, Y, basic_da=700000, hra_received=280000, rent_paid=180000, metro=True, sec_80c=150000), []),
    ("D18", "hinglish", "complete", "Papa ki age 70 hai, unki gross salary 6 lakh saal ki hai. Unka koi deduction nahi hai, na rent na loan.", _gold(600000, S), []),
    ("D19", "hinglish", "complete", "Meri monthly gross salary 2 lakh hai, age 44. Parents ka health insurance 40 hazaar deta hu, dono senior citizen hain. Baaki kuch nahi: no 80C, no NPS, apna insurance nahi, rent nahi, home loan nahi.", _gold(2400000, Y, sec_80d_parents=40000, parents_senior=True), []),
    ("D20", "hinglish", "complete", "Age 30, salary 25 LPA gross. Sirf 80C mein 1 lakh invest kiya hai, aur kuch deduction nahi hai.", _gold(2500000, Y, sec_80c=100000), []),
    # ---------- complete, boundary cap behaviours in words ----------
    ("D21", "english", "complete", "I'm 59, gross salary 16,00,000 a year. I put 2,00,000 in 80C and 75,000 in NPS. Health premium 30,000 for me. Parents' premium 20,000, they are in their fifties. Home loan interest 3,00,000. No rent or HRA.", _gold(1600000, Y, sec_80c=200000, sec_80ccd1b=75000, sec_80d_self=30000, sec_80d_parents=20000, parents_senior=False, home_loan_interest=300000), []),
    ("D22", "english", "complete", "Forty-two years old. Annual gross salary of Rs. 5,50,000. No HRA, no rent, and no tax-saving investments or loans.", _gold(550000, Y), []),
    # ---------- incomplete ----------
    ("D23", "english", "incomplete", "My salary is 12 LPA gross. How much tax do I pay?", None, ["age", "deductions"]),
    ("D24", "english", "incomplete", "I'm 33 years old and want to know which tax regime is better for me.", None, ["salary", "deductions"]),
    ("D25", "english", "incomplete", "My in-hand salary is 85,000 per month and I am 30. I have no deductions.", None, ["salary"]),
    ("D26", "english", "incomplete", "My CTC is 20 lakh. I'm 36. No investments or rent.", None, ["salary"]),
    ("D27", "english", "incomplete", "I'm 29 with a gross salary of 15 LPA. I pay rent in Pune and get HRA. No other deductions.", None, ["hra_details"]),
    ("D28", "english", "incomplete", "Age 40, gross 18 lakh per year. I pay 60,000 a year for my parents' health insurance. No other deductions.", None, ["parents_age"]),
    ("D29", "english", "incomplete", "I earn 9 lakh and I am 27 years old. No investments, no rent, no loans.", None, ["salary"]),
    ("D30", "terse", "incomplete", "tax on 30L?", None, ["age", "deductions"]),
    ("D31", "english", "incomplete", "I'm a senior citizen with gross pay of 8 lakh a year and no deductions.", None, ["age"]),
    ("D32", "english", "incomplete", "I'm 45, gross salary 28 lakh a year. I invest in PPF and pay a home loan.", None, ["deductions"]),
    ("D33", "hinglish", "incomplete", "Meri salary 50 hazaar hai, tax kitna lagega?", None, ["salary", "age", "deductions"]),
    ("D34", "hinglish", "incomplete", "Age 32 hai, gross 16 lakh saal ka. Rent deta hu Delhi mein 30 hazaar mahina, aur baaki koi deduction nahi.", None, ["hra_details"]),
    ("D35", "hinglish", "incomplete", "Mera 80C pura hai aur NPS bhi hai, batao old better hai ya new?", None, ["salary", "age", "deductions"]),
    ("D36", "hinglish", "incomplete", "Haath mein 70k aata hai har mahine, umar 26. Koi deduction nahi.", None, ["salary"]),
    ("D37", "english", "incomplete", "Gross 11 LPA. I'm 34. I have some health insurance, but nothing else.", None, ["deductions"]),
    ("D38", "english", "incomplete", "My parents are 70 and I pay 30,000 for their mediclaim. I'm on 20 LPA gross. No other deductions.", None, ["age"]),
    # ---------- contradictory ----------
    ("D39", "english", "contradictory", "I'm 30 years old. Being 62 I also want the senior citizen slabs. Gross salary 10 LPA, no deductions.", None, ["conflict"]),
    ("D40", "english", "contradictory", "My gross salary is 12 LPA, which is 1.5 lakh gross per month. I'm 35 with no deductions.", None, ["conflict"]),
    ("D41", "english", "contradictory", "Age 28, gross 14 LPA. I don't have a home loan. My home loan interest is 2 lakh a year. No other deductions.", None, ["conflict"]),
    ("D42", "english", "contradictory", "I'm 33, gross 9 LPA. My 80C is 1 lakh. Actually I have made no 80C investments. Nothing else to claim.", None, ["conflict"]),
    ("D43", "hinglish", "contradictory", "Meri age 35 hai aur gross 18 lakh per year. Main rent nahi deta. Har mahine 20 hazaar rent deta hu. Koi aur deduction nahi.", None, ["conflict"]),
    ("D44", "hinglish", "contradictory", "Umar 40 saal, gross 20 LPA. NPS mein 50 hazaar dalta hu, NPS hai hi nahi mera. Baaki kuch nahi.", None, ["conflict"]),
    ("D45", "terse", "contradictory", "age 25, age 52, gross 8L pa, no deductions", None, ["conflict"]),
    # ---------- out of scope ----------
    ("D46", "english", "out_of_scope", "I'm 35 with gross salary of 20 LPA and no deductions. I also made 4 lakh in capital gains from selling shares.", None, ["unsupported"]),
    ("D47", "english", "out_of_scope", "I'm 42, gross salary 15 LPA, plus 6 lakh from my side business. No deductions.", None, ["unsupported"]),
    ("D48", "english", "out_of_scope", "I'm an NRI living in Dubai, age 39, with an Indian salary of 25 LPA gross. No deductions.", None, ["unsupported"]),
    ("D49", "hinglish", "out_of_scope", "Age 38, gross 12 lakh per year salary. Ek flat kiraye pe diya hai, 2 lakh saal ka rent aata hai. Koi deduction nahi.", None, ["unsupported"]),
    ("D50", "hinglish", "out_of_scope", "Main 30 ka hu, gross 10 LPA aur freelancing se 3 lakh extra kamata hu. Koi deduction nahi.", None, ["unsupported"]),
]
