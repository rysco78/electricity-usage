"""
Usage:
    python main.py --bill path/to/bill.pdf --username YOUR_SMT_USER --password YOUR_SMT_PASS

Smart Meter Texas account registration: https://www.smartmetertexas.com
"""

import argparse
import getpass
from collections import defaultdict
from datetime import datetime

from tabulate import tabulate

from parse_bill import extract_bill_data
from smt_client import SMTClient


def aggregate_by_month(daily_rows: list[dict]) -> list[dict]:
    monthly: dict[str, float] = defaultdict(float)
    for row in daily_rows:
        try:
            dt = datetime.strptime(row["date"], "%m/%d/%Y")
        except ValueError:
            continue
        key = dt.strftime("%b %Y")
        monthly[key] += row["kwh"]

    # Sort chronologically
    return [
        {"month": k, "kwh": round(v, 1)}
        for k, v in sorted(monthly.items(), key=lambda x: datetime.strptime(x[0], "%b %Y"))
    ]


def main():
    parser = argparse.ArgumentParser(description="Fetch TX electricity usage from a bill PDF.")
    parser.add_argument("--bill", required=True, help="Path to your electricity bill PDF")
    parser.add_argument("--username", help="Smart Meter Texas username (will prompt if omitted)")
    parser.add_argument("--password", help="Smart Meter Texas password (will prompt if omitted)")
    parser.add_argument("--months", type=int, default=13, help="Months of history to fetch (default: 13)")
    args = parser.parse_args()

    print("Parsing bill...")
    bill = extract_bill_data(args.bill)
    print(f"  ESI ID      : {bill['esi_id']}")
    if bill["billing_period"]:
        print(f"  Last period : {bill['billing_period'][0]} – {bill['billing_period'][1]}")
    if bill["current_usage_kwh"]:
        print(f"  Current bill: {bill['current_usage_kwh']:,} kWh")
    if bill["thirteen_month_total_kwh"]:
        print(f"  13-mo total : {bill['thirteen_month_total_kwh']:,} kWh")

    username = args.username or input("\nSmart Meter Texas username: ")
    password = args.password or getpass.getpass("Smart Meter Texas password: ")

    print("\nAuthenticating with Smart Meter Texas...")
    client = SMTClient(username, password)
    client.authenticate()
    print("  Authenticated.")

    print(f"\nFetching {args.months} months of daily usage for ESI {bill['esi_id']}...")
    daily = client.get_daily_usage(bill["esi_id"], months=args.months)
    print(f"  Retrieved {len(daily)} daily readings.")

    monthly = aggregate_by_month(daily)

    print("\n--- Monthly Usage ---")
    print(tabulate(
        [[r["month"], f"{r['kwh']:,.1f}"] for r in monthly],
        headers=["Month", "kWh"],
        tablefmt="simple",
    ))

    total = sum(r["kwh"] for r in monthly)
    print(f"\nTotal ({len(monthly)} months): {total:,.1f} kWh")
    print(f"Monthly average          : {total / len(monthly):,.1f} kWh")


if __name__ == "__main__":
    main()
