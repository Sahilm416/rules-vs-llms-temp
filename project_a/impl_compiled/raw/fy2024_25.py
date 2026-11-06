from decimal import Decimal

def compute(inp: dict) -> dict:
    if inp.get("fy") != "2024-25":
        raise ValueError("Invalid financial year. This module covers FY 2024-25.")

    age = inp["age"]
    basic_da = Decimal(inp["basic_da"])
    hra_received = Decimal(inp["hra_received"])
    other_salary = Decimal(inp["other_salary"])
    rent_paid = Decimal(inp["rent_paid"])
    metro = inp["metro"]
    sec_80c_in = Decimal(inp["sec_80c"])
    sec_80ccd1b_in = Decimal(inp["sec_80ccd1b"])
    sec_80d_self_in = Decimal(inp["sec_80d_self"])
    sec_80d_parents_in = Decimal(inp["sec_80d_parents"])
    parents_senior = inp["parents_senior"]
    home_loan_interest = Decimal(inp["home_loan_interest"])

    gross_salary = basic_da + hra_received + other_salary

    # HRA Exemption (OLD regime only)
    if rent_paid <= Decimal('0.10') * basic_da or rent_paid == Decimal(0):
        hra_exemption = Decimal(0)
    else:
        clause_a = hra_received
        clause_b = rent_paid - (Decimal('0.10') * basic_da)
        clause_c = (Decimal('0.50') if metro else Decimal('0.40')) * basic_da
        hra_exemption = max(Decimal(0), min(clause_a, clause_b, clause_c))

    def calculate_regime(regime_name: str) -> dict:
        income_trace = []
        tax_trace = []

        income_trace.append({
            "group": "income",
            "clause": "S17",
            "description": "Gross salary",
            "amount": float(gross_salary)
        })

        if regime_name == "old":
            hra_exemp_allowed = hra_exemption
            income_trace.append({
                "group": "income",
                "clause": "S10-13A",
                "description": "House rent allowance exemption",
                "amount": -float(hra_exemp_allowed)
            })
            
            salary_after_hra = max(Decimal(0), gross_salary - hra_exemp_allowed)
            std_deduction = min(salary_after_hra, Decimal(50000))
            income_trace.append({
                "group": "income",
                "clause": "S16-ia",
                "description": "Standard deduction",
                "amount": -float(std_deduction)
            })

            net_salary = max(Decimal(0), salary_after_hra - std_deduction)

            hp_loss_claimed = min(home_loan_interest, Decimal(200000))
            income_trace.append({
                "group": "income",
                "clause": "S24-b",
                "description": "Interest on loan for self-occupied house",
                "amount": -float(hp_loss_claimed)
            })

            if hp_loss_claimed > net_salary:
                hp_loss_restriction = hp_loss_claimed - net_salary
            else:
                hp_loss_restriction = Decimal(0)
            
            if hp_loss_restriction > Decimal(0):
                income_trace.append({
                    "group": "income",
                    "clause": "S71-3A",
                    "description": "House property loss set-off restriction to gross total income limit",
                    "amount": float(hp_loss_restriction)
                })

            gti = max(Decimal(0), net_salary - hp_loss_claimed)

            s80c = min(sec_80c_in, Decimal(150000))
            s80ccd1b = min(sec_80ccd1b_in, Decimal(50000))
            
            limit_self = Decimal(50000) if age >= 60 else Decimal(25000)
            s80d_self = min(sec_80d_self_in, limit_self)

            limit_parents = Decimal(50000) if parents_senior else Decimal(25000)
            s80d_parents = min(sec_80d_parents_in, limit_parents)

            income_trace.append({
                "group": "income",
                "clause": "S80C",
                "description": "Deduction under section 80C",
                "amount": -float(s80c)
            })
            income_trace.append({
                "group": "income",
                "clause": "S80CCD-1B",
                "description": "Contribution to NPS under section 80CCD(1B)",
                "amount": -float(s80ccd1b)
            })
            income_trace.append({
                "group": "income",
                "clause": "S80D-SELF",
                "description": "Health insurance premium for self/family",
                "amount": -float(s80d_self)
            })
            income_trace.append({
                "group": "income",
                "clause": "S80D-PARENTS",
                "description": "Health insurance premium for parents",
                "amount": -float(s80d_parents)
            })

            tot_ch6a_claimed = s80c + s80ccd1b + s80d_self + s80d_parents
            if tot_ch6a_claimed > gti:
                ch6a_excess = tot_ch6a_claimed - gti
                income_trace.append({
                    "group": "income",
                    "clause": "S80A-2",
                    "description": "Cap on total Chapter VI-A deductions to Gross Total Income",
                    "amount": float(ch6a_excess)
                })
                ch6a_deduction = gti
            else:
                ch6a_deduction = tot_ch6a_claimed

            ti_unrounded = gti - ch6a_deduction

        else: # NEW regime
            income_trace.append({
                "group": "income",
                "clause": "S10-13A",
                "description": "House rent allowance exemption (not allowed under new regime)",
                "amount": 0.0
            })

            std_deduction = min(gross_salary, Decimal(75000))
            income_trace.append({
                "group": "income",
                "clause": "S16-ia",
                "description": "Standard deduction",
                "amount": -float(std_deduction)
            })

            income_trace.append({
                "group": "income",
                "clause": "S24-b",
                "description": "Interest on home loan (not allowed under new regime)",
                "amount": 0.0
            })

            income_trace.append({
                "group": "income",
                "clause": "S80C",
                "description": "Deduction under section 80C (not allowed under new regime)",
                "amount": 0.0
            })
            income_trace.append({
                "group": "income",
                "clause": "S80CCD-1B",
                "description": "Contribution to NPS (not allowed under new regime)",
                "amount": 0.0
            })
            income_trace.append({
                "group": "income",
                "clause": "S80D-SELF",
                "description": "Health insurance for self/family (not allowed under new regime)",
                "amount": 0.0
            })
            income_trace.append({
                "group": "income",
                "clause": "S80D-PARENTS",
                "description": "Health insurance for parents (not allowed under new regime)",
                "amount": 0.0
            })

            gti = max(Decimal(0), gross_salary - std_deduction)
            ti_unrounded = gti

        # Income Rounding S288A
        ti_int = int(ti_unrounded)
        rem = ti_int % 10
        if rem >= 5:
            total_income_int = ti_int + (10 - rem)
        else:
            total_income_int = ti_int - rem

        ti_decimal = Decimal(total_income_int)
        rounding_s288a = ti_decimal - ti_unrounded
        income_trace.append({
            "group": "income",
            "clause": "S288A",
            "description": "Rounding off total income under section 288A",
            "amount": float(rounding_s288a)
        })

        # Slab Tax Computation
        def get_slab_tax_and_trace(ti: Decimal, reg: str, user_age: int):
            slabs_info = []
            if reg == "new":
                slabs_info = [
                    (Decimal(0), Decimal(300000), Decimal('0.00'), "S115BAC-1A-ii-S1", "Tax slab up to Rs 3,00,000 (0%)"),
                    (Decimal(300000), Decimal(700000), Decimal('0.05'), "S115BAC-1A-ii-S2", "Tax slab Rs 3,00,001 to Rs 7,00,000 (5%)"),
                    (Decimal(700000), Decimal(1000000), Decimal('0.10'), "S115BAC-1A-ii-S3", "Tax slab Rs 7,00,001 to Rs 10,00,000 (10%)"),
                    (Decimal(1000000), Decimal(1200000), Decimal('0.15'), "S115BAC-1A-ii-S4", "Tax slab Rs 10,00,001 to Rs 12,00,000 (15%)"),
                    (Decimal(1200000), Decimal(1500000), Decimal('0.20'), "S115BAC-1A-ii-S5", "Tax slab Rs 12,00,001 to Rs 15,00,000 (20%)"),
                    (Decimal(1500000), Decimal('Infinity'), Decimal('0.30'), "S115BAC-1A-ii-S6", "Tax slab above Rs 15,00,000 (30%)")
                ]
            else:
                if user_age < 60:
                    slabs_info = [
                        (Decimal(0), Decimal(250000), Decimal('0.00'), "FS3-A-i-S1", "Tax slab up to Rs 2,50,000 (0%)"),
                        (Decimal(250000), Decimal(500000), Decimal('0.05'), "FS3-A-i-S2", "Tax slab Rs 2,50,001 to Rs 5,00,000 (5%)"),
                        (Decimal(500000), Decimal(1000000), Decimal('0.20'), "FS3-A-i-S3", "Tax slab Rs 5,00,001 to Rs 10,00,000 (20%)"),
                        (Decimal(1000000), Decimal('Infinity'), Decimal('0.30'), "FS3-A-i-S4", "Tax slab above Rs 10,00,000 (30%)")
                    ]
                elif user_age < 80:
                    slabs_info = [
                        (Decimal(0), Decimal(300000), Decimal('0.00'), "FS3-A-ii-S1", "Tax slab up to Rs 3,00,000 (0%)"),
                        (Decimal(300000), Decimal(500000), Decimal('0.05'), "FS3-A-ii-S2", "Tax slab Rs 3,00,001 to Rs 5,00,000 (5%)"),
                        (Decimal(500000), Decimal(1000000), Decimal('0.20'), "FS3-A-ii-S3", "Tax slab Rs 5,00,001 to Rs 10,00,000 (20%)"),
                        (Decimal(1000000), Decimal('Infinity'), Decimal('0.30'), "FS3-A-ii-S4", "Tax slab above Rs 10,00,000 (30%)")
                    ]
                else:
                    slabs_info = [
                        (Decimal(0), Decimal(500000), Decimal('0.00'), "FS3-A-iii-S1", "Tax slab up to Rs 5,00,000 (0%)"),
                        (Decimal(500000), Decimal(1000000), Decimal('0.20'), "FS3-A-iii-S2", "Tax slab Rs 5,00,001 to Rs 10,00,000 (20%)"),
                        (Decimal(1000000), Decimal('Infinity'), Decimal('0.30'), "FS3-A-iii-S3", "Tax slab above Rs 10,00,000 (30%)")
                    ]

            total_slab_tax = Decimal(0)
            traces = []
            for lower, upper, rate, clause_id, desc in slabs_info:
                if ti > lower:
                    taxable_in_slab = min(ti, upper) - lower
                    tax_in_slab = taxable_in_slab * rate
                    total_slab_tax += tax_in_slab
                    traces.append({
                        "group": "tax",
                        "clause": clause_id,
                        "description": desc,
                        "amount": float(tax_in_slab)
                    })
            return total_slab_tax, traces

        slab_tax, slab_traces = get_slab_tax_and_trace(ti_decimal, regime_name, age)
        tax_trace.extend(slab_traces)

        # Rebate 87A
        rebate = Decimal(0)
        rebate_clause = ""
        rebate_desc = ""

        if regime_name == "old":
            if ti_decimal <= Decimal(500000):
                rebate = min(slab_tax, Decimal(12500))
            else:
                rebate = Decimal(0)
            rebate_clause = "S87A-OLD"
            rebate_desc = "Rebate under section 87A"
        else:
            if ti_decimal <= Decimal(700000):
                rebate = min(slab_tax, Decimal(25000))
                rebate_clause = "S87A-NEW-a"
                rebate_desc = "Rebate under section 87A"
            else:
                excess_income = ti_decimal - Decimal(700000)
                if slab_tax > excess_income:
                    rebate = slab_tax - excess_income
                else:
                    rebate = Decimal(0)
                rebate_clause = "S87A-NEW-b"
                rebate_desc = "Marginal relief rebate under section 87A"

        tax_trace.append({
            "group": "tax",
            "clause": rebate_clause,
            "description": rebate_desc,
            "amount": -float(rebate)
        })

        tax_after_rebate = slab_tax - rebate

        # Surcharge & Marginal Relief
        surcharge_rate = Decimal(0)
        surcharge_clause = ""
        surcharge_desc = ""
        T_limit = Decimal(0)

        if ti_decimal > Decimal(50000000):
            if regime_name == "old":
                surcharge_rate = Decimal('0.37')
                surcharge_clause = "SURCH-5CR-OLD"
                surcharge_desc = "Surcharge at 37% for income above Rs 5 crore"
            else:
                surcharge_rate = Decimal('0.25')
                surcharge_clause = "SURCH-5CR-NEW"
                surcharge_desc = "Surcharge at 25% for income above Rs 5 crore"
            T_limit = Decimal(50000000)
        elif ti_decimal > Decimal(20000000):
            surcharge_rate = Decimal('0.25')
            surcharge_clause = "SURCH-2CR"
            surcharge_desc = "Surcharge at 25% for income above Rs 2 crore"
            T_limit = Decimal(20000000)
        elif ti_decimal > Decimal(10000000):
            surcharge_rate = Decimal('0.15')
            surcharge_clause = "SURCH-1CR"
            surcharge_desc = "Surcharge at 15% for income above Rs 1 crore"
            T_limit = Decimal(10000000)
        elif ti_decimal > Decimal(5000000):
            surcharge_rate = Decimal('0.10')
            surcharge_clause = "SURCH-50L"
            surcharge_desc = "Surcharge at 10% for income above Rs 50 lakh"
            T_limit = Decimal(5000000)

        raw_surcharge = tax_after_rebate * surcharge_rate
        marginal_relief = Decimal(0)

        if surcharge_rate > Decimal(0):
            tax_trace.append({
                "group": "tax",
                "clause": surcharge_clause,
                "description": surcharge_desc,
                "amount": float(raw_surcharge)
            })

            # Calculate tax + surcharge at T_limit
            tax_at_T, _ = get_slab_tax_and_trace(T_limit, regime_name, age)
            # Rebate at T_limit (>= 50L) is 0
            # Surcharge rate at exactly T_limit:
            if T_limit == Decimal(5000000):
                surch_rate_at_T = Decimal(0)
            elif T_limit == Decimal(10000000):
                surch_rate_at_T = Decimal('0.10')
            elif T_limit == Decimal(20000000):
                surch_rate_at_T = Decimal('0.15')
            elif T_limit == Decimal(50000000):
                surch_rate_at_T = Decimal('0.25')
            else:
                surch_rate_at_T = Decimal(0)

            surch_at_T = tax_at_T * surch_rate_at_T
            max_tax_and_surcharge = tax_at_T + surch_at_T + (ti_decimal - T_limit)

            current_tax_and_surcharge = tax_after_rebate + raw_surcharge
            if current_tax_and_surcharge > max_tax_and_surcharge:
                marginal_relief = current_tax_and_surcharge - max_tax_and_surcharge

            if marginal_relief > Decimal(0):
                tax_trace.append({
                    "group": "tax",
                    "clause": "SURCH-MR",
                    "description": "Marginal relief on surcharge",
                    "amount": -float(marginal_relief)
                })

        final_surcharge = raw_surcharge - marginal_relief

        # Cess
        tax_plus_surcharge = tax_after_rebate + final_surcharge
        cess = tax_plus_surcharge * Decimal('0.04')

        tax_trace.append({
            "group": "tax",
            "clause": "CESS",
            "description": "Health and Education Cess at 4%",
            "amount": float(cess)
        })

        total_before_rounding = tax_plus_surcharge + cess

        # Final Rounding S288B
        tbr_int = int(total_before_rounding)
        rem_b = tbr_int % 10
        if rem_b >= 5:
            tax_payable_int = tbr_int + (10 - rem_b)
        else:
            tax_payable_int = tbr_int - rem_b

        rounding_s288b = Decimal(tax_payable_int) - total_before_rounding
        tax_trace.append({
            "group": "tax",
            "clause": "S288B",
            "description": "Rounding off tax payable under section 288B",
            "amount": float(rounding_s288b)
        })

        return {
            "total_income": total_income_int,
            "slab_tax": float(slab_tax),
            "rebate": float(rebate),
            "surcharge": float(final_surcharge),
            "cess": float(cess),
            "total_before_rounding": float(total_before_rounding),
            "tax_payable": tax_payable_int,
            "trace": income_trace + tax_trace
        }

    res_old = calculate_regime("old")
    res_new = calculate_regime("new")

    if res_old["tax_payable"] < res_new["tax_payable"]:
        recommended = "old"
    else:
        recommended = "new"

    return {
        "old": res_old,
        "new": res_new,
        "recommended": recommended
    }
