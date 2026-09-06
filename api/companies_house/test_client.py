"""
Standalone test for the Companies House client.
"""

from pprint import pprint
import argparse

from companies_house.ingestion import fetch_company


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "company_name",
        help="Company name to search"
    )
    args = parser.parse_args()

    results = fetch_company(args.company_name)

    print(f"\nFound {len(results)} companies\n")

    for company in results:
        pprint(company.model_dump())
        print("-" * 80)

if __name__ == "__main__":
    main()