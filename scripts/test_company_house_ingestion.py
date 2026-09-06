from api.company_house.ingestion import (
    CompanyHouseIngestion,
)


def main() -> None:

    ingestion = CompanyHouseIngestion()

    ingestion.ingest_company(
        "TechVault Solutions Ltd"
    )

    print("Done.")


if __name__ == "__main__":
    main()