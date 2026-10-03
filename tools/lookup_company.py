"""
Looks a company up in Companies House and prints what comes back.

For checking by hand what the API returns for a given name - useful when a
company in a CV is not matching, to see whether the API knows it at all and
under what spelling. Reads only; writes nothing.

    python tools/lookup_company.py "TechVault Solutions Ltd"
"""

from pprint import pprint
import argparse

from external.companies_house.ingestion import fetch_company


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
