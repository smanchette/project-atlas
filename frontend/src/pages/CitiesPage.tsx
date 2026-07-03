import { FormEvent, useEffect, useMemo, useState } from "react";

import { listItems, updateItem } from "../api";
import type { City, County } from "../types";

type CityFormState = Pick<City, "priority" | "is_primary_market" | "status"> & { notes: string };

const priorities: City["priority"][] = ["Primary", "High", "Medium", "Low"];

function CitiesPage() {
  const [cities, setCities] = useState<City[]>([]);
  const [counties, setCounties] = useState<County[]>([]);
  const [selected, setSelected] = useState<City | null>(null);
  const [countyFilter, setCountyFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [formState, setFormState] = useState<CityFormState>({
    priority: "Medium",
    notes: "",
    status: "active",
    is_primary_market: false
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [cityData, countyData] = await Promise.all([listItems<City>("/api/cities"), listItems<County>("/api/counties")]);
      setCities(cityData);
      setCounties(countyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load cities.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const countyNameById = useMemo(() => {
    return new Map(counties.map((county) => [county.id, county.county_name]));
  }, [counties]);

  const filteredCities = cities.filter((city) => {
    const countyMatches = countyFilter === "all" || String(city.county_id) === countyFilter;
    const priorityMatches = priorityFilter === "all" || city.priority === priorityFilter;
    return countyMatches && priorityMatches;
  });

  function editCity(city: City) {
    setSelected(city);
    setFormState({
      priority: city.priority,
      notes: city.notes ?? "",
      status: city.status,
      is_primary_market: city.is_primary_market
    });
  }

  function resetForm() {
    setSelected(null);
    setFormState({ priority: "Medium", notes: "", status: "active", is_primary_market: false });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateItem<City>("/api/cities", selected.id, formState);
      resetForm();
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update city.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Manage</p>
          <h1>Cities</h1>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}

      <div className="moduleGrid">
        <section className="panel">
          <h2>{selected ? `Edit ${selected.city_name}` : "City Details"}</h2>
          {selected ? (
            <form className="recordForm" onSubmit={handleSubmit}>
              <label>
                <span>Priority</span>
                <select
                  value={formState.priority}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, priority: event.target.value as City["priority"] }))
                  }
                >
                  {priorities.map((priority) => (
                    <option key={priority} value={priority}>
                      {priority}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Status</span>
                <input value={formState.status} onChange={(event) => setFormState((current) => ({ ...current, status: event.target.value }))} />
              </label>
              <label className="checkboxLabel">
                <input
                  type="checkbox"
                  checked={formState.is_primary_market}
                  onChange={(event) => setFormState((current) => ({ ...current, is_primary_market: event.target.checked }))}
                />
                <span>Primary market</span>
              </label>
              <label>
                <span>Notes</span>
                <textarea value={formState.notes} onChange={(event) => setFormState((current) => ({ ...current, notes: event.target.value }))} />
              </label>
              <div className="formActions">
                <button className="primaryButton" type="submit" disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </button>
                <button className="secondaryButton" type="button" onClick={resetForm}>
                  Clear
                </button>
              </div>
            </form>
          ) : (
            <p>Select a city to edit priority, notes, status, or primary-market flag.</p>
          )}
        </section>

        <section className="panel tablePanel">
          <div className="panelHeader">
            <h2>City Records</h2>
            <span className="countBadge">{filteredCities.length} shown</span>
          </div>
          <div className="filterBar">
            <label>
              <span>County</span>
              <select value={countyFilter} onChange={(event) => setCountyFilter(event.target.value)}>
                <option value="all">All counties</option>
                {counties.map((county) => (
                  <option key={county.id} value={county.id}>
                    {county.county_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Priority</span>
              <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
                <option value="all">All priorities</option>
                {priorities.map((priority) => (
                  <option key={priority} value={priority}>
                    {priority}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {loading ? (
            <p>Loading cities...</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>City</th>
                    <th>County</th>
                    <th>State</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Primary</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCities.map((city) => (
                    <tr key={city.id}>
                      <td>{city.city_name}</td>
                      <td>{countyNameById.get(city.county_id) ?? city.county_id}</td>
                      <td>{city.state}</td>
                      <td>{city.priority}</td>
                      <td>{city.status}</td>
                      <td>{city.is_primary_market ? "Yes" : "No"}</td>
                      <td>
                        <button className="linkButton" type="button" onClick={() => editCity(city)}>
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

export default CitiesPage;
