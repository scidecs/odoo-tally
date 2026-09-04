# -*- coding: utf-8 -*-
"""Constants, selections, and entity mappings for Tally integration."""

ENTITY_SELECTION = [
    ("group", "Account Group"),
    ("ledger", "Party Ledger (Customer/Vendor)"),
    ("account_ledger", "Account Ledger (General Ledger)"),
    ("uom", "Unit of Measure"),
    ("stock_group", "Stock Category / Group"),
    ("stock_item", "Stock Item (Product)"),
    ("godown", "Godown / Location"),
    ("cost_centre", "Cost Centre / Analytic Account"),
    ("tax", "Tax / GST Rate"),
    ("currency", "Currency & Exchange Rate"),
    ("opening_balance", "Opening Balance"),
    ("sales", "Sales Voucher (Invoice)"),
    ("credit_note", "Credit Note Voucher"),
    ("purchase", "Purchase Voucher (Bill)"),
    ("debit_note", "Debit Note Voucher"),
    ("receipt", "Receipt Voucher (Payment In)"),
    ("payment", "Payment Voucher (Payment Out)"),
    ("journal", "Journal Voucher"),
    ("contra", "Contra Voucher"),
    ("stock_journal", "Stock Journal / Transfer"),
]

SOURCE_OF_TRUTH_SELECTION = [
    ("tally", "Tally (accounting system master)"),
    ("odoo", "Odoo (ERP master)"),
    ("tally_master", "Tally master (Odoo read-only)"),
    ("bidirectional", "Bidirectional (serialized arrival order)"),
]

DIRECTION_SELECTION = [
    ("tally_to_odoo", "Tally → Odoo"),
    ("odoo_to_tally", "Odoo → Tally"),
    ("both", "Two-way"),
]

ACCOUNT_TYPE_SELECTION = [
    ("asset_receivable", "Receivable"),
    ("asset_cash", "Bank and Cash"),
    ("asset_current", "Current Assets"),
    ("asset_non_current", "Non-current Assets"),
    ("asset_prepayments", "Prepayments"),
    ("asset_fixed", "Fixed Assets"),
    ("liability_payable", "Payable"),
    ("liability_credit_card", "Credit Card"),
    ("liability_current", "Current Liabilities"),
    ("liability_non_current", "Non-current Liabilities"),
    ("equity", "Equity"),
    ("equity_unaffected", "Current Year Earnings"),
    ("income", "Income"),
    ("income_other", "Other Income"),
    ("expense", "Expenses"),
    ("expense_depreciation", "Depreciation"),
    ("expense_direct_cost", "Cost of Revenue"),
    ("off_balance", "Off-Balance Sheet"),
]

# Default entity registration: (entity, odoo_model, default_source_of_truth, sequence)
DEFAULT_ENTITIES = [
    ("group", "account.group", "tally", 10),
    ("account_ledger", "account.account", "tally", 20),
    ("ledger", "res.partner", "bidirectional", 30),
    ("uom", "uom.uom", "bidirectional", 40),
    ("stock_group", "product.category", "bidirectional", 45),
    ("stock_item", "product.product", "bidirectional", 50),
    ("godown", "stock.location", "bidirectional", 55),
    ("cost_centre", "account.analytic.account", "bidirectional", 60),
    ("tax", "account.tax", "tally", 70),
    ("currency", "res.currency", "tally", 80),
    ("opening_balance", "account.move", "tally", 90),
    ("sales", "account.move", "tally", 100),
    ("credit_note", "account.move", "tally", 105),
    ("purchase", "account.move", "tally", 110),
    ("debit_note", "account.move", "tally", 115),
    ("receipt", "account.payment", "tally", 120),
    ("payment", "account.payment", "tally", 130),
    ("journal", "account.move", "tally", 140),
    ("contra", "account.move", "tally", 150),
    ("stock_journal", "stock.picking", "tally", 160),
]


def direction_for_source(source_of_truth):
    """Sensible default sync direction implied by a source-of-truth choice."""
    if source_of_truth in ("tally", "tally_master"):
        return "tally_to_odoo"
    if source_of_truth == "odoo":
        return "odoo_to_tally"
    return "both"


INDIAN_GST_STATE_CODES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}

TDS_SECTIONS = {
    "194C": "Payment to Contractors",
    "194J": "Fees for Professional / Technical Services",
    "194I": "Rent on Land / Building / Machinery",
    "194Q": "TDS on Purchase of Goods",
    "194H": "Commission or Brokerage",
    "194A": "Interest other than Securities",
    "194DA": "Payment in respect of Life Insurance Policy",
    "194M": "Payment to Commission / Brokerage / Contractors by Ind / HUF",
    "206C": "TCS on Sale of Goods / Scrap / Minerals",
    "206C(1H)": "TCS on Sale of Goods exceeding 50L",
}
