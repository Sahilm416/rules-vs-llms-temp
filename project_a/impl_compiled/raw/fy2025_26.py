from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
import math

def compute(inp: dict) -> dict:
    if inp.get("fy") != "2025-26":
        raise ValueError("Invalid financial year, expected 2025-26")

    age = inp.get("age", 0)
    basic_da = inp.get("basic_da", 0)
    hra_received = inp.get("hra_received", 0)
    other_salary = inp.get("other_salary", 0)
    rent_paid = inp.get("rent_paid", 0)
    metro = inp.get("metro", False)
    sec_80c = inp.get("sec_80c", 0)
    sec_80ccd1b = inp.get("sec_80ccd1b", 0)
    sec_80d_self = inp.get("sec_80d_self", 0)
    sec_80d_parents = inp.get("sec_80d_parents", 0)
    parents_senior = inp.get("parents_senior", False)
    home_loan_interest = inp.get("home_loan_interest", 0)

    def round_nearest_10(amount_float: float) -> int:
        d = Decimal(str(amount_float))
        d_quantized = d.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        rem = d_quantized % 10
        if rem >= 5:
            res = d_quantized + (10 - rem)
        else:
            res = d_quantized - rem
        return int(res)

    def run_regime(regime: str) -> dict:
        trace = []
        
        # [S17] Gross salary
        gross_salary = basic_da + hra_received + other_salary
        trace.append({
            "group": "income",
            "clause": "S17",
            "description": "Gross salary (basic, DA, HRA, and other salary)",
            "amount": float(gross_salary)
        })

        if regime == "old":
            # HRA exemption [S10-13A]
            if rent_paid <= 0 or rent_paid <= Decimal(0.10) * basic_da:
                hra_exemp = 0
            else:
                cond_a = hra_received
                cond_b = rent_paid - int(Decimal(0.10) * basic_da)
                cond_c = int(Decimal('0.50') * basic_da) if metro else int(Decimal('0.40') * basic_da)
                hra_exemp = min(cond_a, cond_b, cond_c)
            
            if hra_exemp > 0:
                trace.append({
                    "group": "income",
                    "clause": "S10-13A",
                    "description": "House rent allowance exemption",
                    "amount": -float(hra_exemp)
                })
            
            salary_after_hra = gross_salary - hra_exemp

            # Standard deduction [S16-ia] (old: 50,000)
            std_ded = min(salary_after_hra, 50000)
            if std_ded > 0:
                trace.append({
                    "group": "income",
                    "clause": "S16-ia",
                    "description": "Standard deduction",
                    "amount": -float(std_ded)
                })
            
            salary_after_std = salary_after_hra - std_ded

            # [S24-b] Interest on self-occupied house
            hp_deduction = min(home_loan_interest, 200000)
            if hp_deduction > 0:
                trace.append({
                    "group": "income",
                    "clause": "S24-b",
                    "description": "Interest on self-occupied house property (loss set-off under S71-3A)",
                    "amount": -float(hp_deduction)
                })
            
            gti = max(0, salary_after_std - hp_deduction)

            # Chapter VI-A deductions
            # S80C: up to 1,50,000
            d_80c = min(sec_80c, 150000)
            if d_80c > 0:
                trace.append({
                    "group": "income",
                    "clause": "S80C",
                    "description": "Deduction under section 80C",
                    "amount": -float(d_80c)
                })

            # S80CCD-1B: up to 50,000
            d_80ccd1b = min(sec_80ccd1b, 50000)
            if d_80ccd1b > 0:
                trace.append({
                    "group": "income",
                    "clause": "S80CCD-1B",
                    "description": "Deduction under section 80CCD(1B)",
                    "amount": -float(d_80ccd1b)
                })

            # S80D-SELF: limit 50,000 if age >= 60 else 25,000
            limit_self = 50000 if age >= 60 else 25000
            d_80d_self = min(sec_80d_self, limit_self)
            if d_80d_self > 0:
                trace.append({
                    "group": "income",
                    "clause": "S80D-SELF",
                    "description": "Health insurance deduction for self and family",
                    "amount": -float(d_80d_self)
                })

            # S80D-PARENTS: limit 50,000 if parents_senior else 25,000
            limit_parents = 50000 if parents_senior else 25000
            d_80d_parents = min(sec_80d_parents, limit_parents)
            if d_80d_parents > 0:
                trace.append({
                    "group": "income",
                    "clause": "S80D-PARENTS",
                    "description": "Health insurance deduction for parents",
                    "amount": -float(d_80d_parents)
                })

            total_via = d_80c + d_80ccd1b + d_80d_self + d_80d_parents
            # S80A-2: Total deductions cannot exceed GTI
            total_via = min(total_via, gti)
            if total_via > 0 and (d_80c + d_80ccd1b + d_80d_self + d_80d_parents) > gti:
                # If capped by GTI, we just represent it as total via
                pass

            total_income_raw = max(0, gti - total_via)

        else:
            # NEW regime: no HRA [S115BAC-2], no S24-b [S115BAC-2], no Chapter VI-A [S115BAC-2]
            std_ded = min(gross_salary, 75000)
            if std_ded > 0:
                trace.append({
                    "group": "income",
                    "clause": "S16-ia",
                    "description": "Standard deduction",
                    "amount": -float(std_ded)
                })
            gti = max(0, gross_salary - std_ded)
            total_income_raw = gti

        # [S288A] Round total income
        total_income = round_nearest_10(float(total_income_raw))
        diff_288a = total_income - total_income_raw
        if diff_288a != 0:
            trace.append({
                "group": "income",
                "clause": "S288A",
                "description": "Rounding of total income to nearest multiple of Rs 10",
                "amount": float(diff_288a)
            })

        # Calculate slab tax
        def calc_slab_tax(inc: int, reg: str, ag: int) -> float:
            tax = 0.0
            if reg == "new":
                # [S115BAC-1A-iii-S1 to S7]
                brackets = [
                    (400000, 0.0),
                    (800000, 0.05),
                    (1200000, 0.10),
                    (1600000, 0.15),
                    (2000000, 0.20),
                    (2400000, 0.25),
                    (float('inf'), 0.30)
                ]
                prev = 0
                for limit, rate in brackets:
                    if inc > prev:
                        taxable_part = min(inc, limit) - prev
                        tax += taxable_part * rate
                        prev = limit
                    else:
                        break
            else:
                if ag >= 80:
                    brackets = [
                        (500000, 0.0),
                        (1000000, 0.20),
                        (float('inf'), 0.30)
                    ]
                elif ag >= 60:
                    brackets = [
                        (300000, 0.0),
                        (500000, 0.05),
                        (1000000, 0.20),
                        (float('inf'), 0.30)
                    ]
                else:
                    brackets = [
                        (250000, 0.0),
                        (500000, 0.05),
                        (1000000, 0.20),
                        (float('inf'), 0.30)
                    ]
                prev = 0
                for limit, rate in brackets:
                    if inc > prev:
                        taxable_part = min(inc, limit) - prev
                        tax += taxable_part * rate
                        prev = limit
                    else:
                        break
            return tax

        slab_tax = calc_slab_tax(total_income, regime, age)
        if slab_tax > 0:
            trace.append({
                "group": "tax",
                "clause": "S115BAC-1A-iii-S1" if regime == "new" else "FS3-A-i-S1",
                "description": "Income tax on total income",
                "amount": float(slab_tax)
            })

        # Rebate S87A
        rebate = 0.0
        if regime == "old":
            if total_income <= 500000:
                rebate = min(slab_tax, 12500.0)
                if rebate > 0:
                    trace.append({
                        "group": "tax",
                        "clause": "S87A-OLD",
                        "description": "Rebate under section 87A",
                        "amount": -float(rebate)
                    })
        else:
            if total_income <= 1200000:
                rebate = min(slab_tax, 60000.0)
                if rebate > 0:
                    trace.append({
                        "group": "tax",
                        "clause": "S87A-NEW-a",
                        "description": "Rebate under section 87A",
                        "amount": -float(rebate)
                    })
            elif total_income > 1200000:
                # Marginal relief for new regime rebate [S87A-NEW-b]
                excess_income = total_income - 1200000
                potential_rebate = max(0.0, slab_tax - excess_income)
                if potential_rebate > 0:
                    rebate = potential_rebate
                    trace.append({
                        "group": "tax",
                        "clause": "S87A-NEW-b",
                        "description": "Rebate under section 87A (marginal relief)",
                        "amount": -float(rebate)
                    })

        tax_after_rebate = max(0.0, slab_tax - rebate)

        # Surcharge
        surcharge = 0.0
        if total_income > 5000000:
            if total_income <= 10000000:
                s_rate = 0.10
                s_clause = "SURCH-50L"
            elif total_income <= 20000000:
                s_rate = 0.15
                s_clause = "SURCH-1CR"
            elif total_income <= 50000000:
                s_rate = 0.25
                s_clause = "SURCH-2CR"
            else:
                if regime == "old":
                    s_rate = 0.37
                    s_clause = "SURCH-5CR-OLD"
                else:
                    s_rate = 0.25
                    s_clause = "SURCH-5CR-NEW"
            
            surcharge = tax_after_rebate * s_rate

            # Marginal Relief [SURCH-MR]
            # Determine threshold T
            if total_income <= 10000000:
                T = 5000000
            elif total_income <= 20000000:
                T = 10000000
            elif total_income <= 50000000:
                T = 20000000
            else:
                T = 50000000

            # Tax plus surcharge on T
            tax_at_T_slab = calc_slab_tax(T, regime, age)
            # Rebate at T? T > 12L (new) or 5L (old), so rebate at T is 0.
            tax_at_T_after_rebate = tax_at_T_slab # assuming no rebate at T
            
            if T <= 10000000:
                t_rate = 0.10 if T == 5000000 else 0.15
            elif T <= 20000000:
                t_rate = 0.15 if T == 10000000 else 0.25
            elif T <= 50000000:
                t_rate = 0.25
            else:
                t_rate = 0.37 if regime == "old" else 0.25

            surcharge_at_T = tax_at_T_after_rebate * t_rate
            total_at_T = tax_at_T_after_rebate + surcharge_at_T
            max_allowed = total_at_T + (total_income - T)

            current_total = tax_after_rebate + surcharge
            if current_total > max_allowed:
                excess = current_total - max_allowed
                surcharge = max(0.0, surcharge - excess)

            if surcharge > 0:
                trace.append({
                    "group": "tax",
                    "clause": s_clause,
                    "description": "Surcharge (with marginal relief if applicable)",
                    "amount": float(surcharge)
                })

        # Cess [CESS]
        tax_plus_surcharge = tax_after_rebate + surcharge
        cess = tax_plus_surcharge * 0.04
        if cess > 0:
            trace.append({
                "group": "tax",
                "clause": "CESS",
                "description": "Health and Education Cess (4%)",
                "amount": float(cess)
            })

        total_before_rounding = tax_plus_surcharge + cess

        # [S288B] Round final tax payable
        tax_payable = round_nearest_10(total_before_rounding)
        diff_288b = tax_payable - total_before_rounding
        if diff_288b != 0:
            trace.append({
                "group": "tax",
                "clause": "S288B",
                "description": "Rounding of final tax payable to nearest multiple of Rs 10",
                "amount": float(diff_288b)
            })

        return {
            "total_income": int(total_income),
            "slab_tax": float(slab_tax),
            "rebate": float(rebate),
            "surcharge": float(surcharge),
            "cess": float(cess),
            "total_before_rounding": float(total_before_rounding),
            "tax_payable": int(tax_payable),
            "trace": trace
        }

    old_result = run_regime("old")
    new_result = run_regime("new")

    # [S115BAC-1A] Recommendation: recommend regime with lower tax payable. If equal, recommend new.
    if old_result["tax_payable"] < new_result["tax_payable"]:
        recommended = "old"
    else:
        recommended = "new"

    return {
        "old": old_result,
        "new": new_result,
        "recommended": recommended
    }
