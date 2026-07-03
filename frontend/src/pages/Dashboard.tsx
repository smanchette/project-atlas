import { useEffect, useState } from "react";

import { listItems } from "../api";
import type { Business, City, County, GeneratedPage, ImageMetadata, Service } from "../types";

type Summary = {
  businesses: Business[];
  services: Service[];
  counties: County[];
  cities: City[];
  pages: GeneratedPage[];
  images: ImageMetadata[];
};

const emptySummary: Summary = {
  businesses: [],
  services: [],
  counties: [],
  cities: [],
  pages: [],
  images: []
};

function Dashboard() {
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [businesses, services, counties, cities, pages, images] = await Promise.all([
          listItems<Business>("/api/businesses"),
          listItems<Service>("/api/services"),
          listItems<County>("/api/counties"),
          listItems<City>("/api/cities"),
          listItems<GeneratedPage>("/api/generated-pages"),
          listItems<ImageMetadata>("/api/image-metadata")
        ]);
        setSummary({ businesses, services, counties, cities, pages, images });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load dashboard.");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  const business = summary.businesses[0];
  const service = summary.services[0];

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>Project Atlas</h1>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      {loading ? (
        <div className="panel">Loading dashboard...</div>
      ) : (
        <>
          <div className="summaryGrid">
            <SummaryTile label="Businesses" value={summary.businesses.length} />
            <SummaryTile label="Services" value={summary.services.length} />
            <SummaryTile label="Counties" value={summary.counties.length} />
            <SummaryTile label="Cities" value={summary.cities.length} />
            <SummaryTile label="Pages" value={summary.pages.length} />
            <SummaryTile label="Images" value={summary.images.length} />
          </div>

          <div className="dashboardGrid">
            <section className="panel">
              <h2>First Business</h2>
              {business ? (
                <dl className="detailsList">
                  <div>
                    <dt>Company</dt>
                    <dd>{business.company_name}</dd>
                  </div>
                  <div>
                    <dt>Market</dt>
                    <dd>
                      {business.main_city}, {business.state}
                    </dd>
                  </div>
                  <div>
                    <dt>Phone</dt>
                    <dd>{business.phone}</dd>
                  </div>
                  <div>
                    <dt>License</dt>
                    <dd>{business.license_number}</dd>
                  </div>
                </dl>
              ) : (
                <p>No business records yet.</p>
              )}
            </section>

            <section className="panel">
              <h2>Primary Service</h2>
              {service ? (
                <dl className="detailsList">
                  <div>
                    <dt>Service</dt>
                    <dd>{service.service_name}</dd>
                  </div>
                  <div>
                    <dt>Slug</dt>
                    <dd>{service.service_slug}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>{service.status}</dd>
                  </div>
                </dl>
              ) : (
                <p>No service records yet.</p>
              )}
            </section>
          </div>
        </>
      )}
    </section>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="summaryTile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default Dashboard;

