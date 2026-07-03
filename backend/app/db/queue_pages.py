from sqlmodel import Session

from app.db.seed import FLO_ZONE_COMPANY_NAME
from app.db.session import create_db_and_tables, engine
from app.services.page_queue import create_city_service_page_queue


def main() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        created_count = create_city_service_page_queue(
            session,
            business_company_name=FLO_ZONE_COMPANY_NAME,
            service_slug="drywood-termite-tenting",
        )
    print(f"Created {created_count} drywood termite tenting city-service draft pages.")


if __name__ == "__main__":
    main()

