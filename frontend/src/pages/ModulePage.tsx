import { FormEvent, useEffect, useMemo, useState } from "react";

import { createItem, deleteItem, listItems, updateItem } from "../api";
import type { FieldConfig } from "../types";

type RecordShape = {
  id: number;
  [key: string]: unknown;
};

type ModulePageProps<T extends RecordShape> = {
  title: string;
  endpoint: string;
  fields: FieldConfig<T>[];
  tableColumns: (keyof T)[];
};

function ModulePage<T extends RecordShape>({ title, endpoint, fields, tableColumns }: ModulePageProps<T>) {
  const [items, setItems] = useState<T[]>([]);
  const [selected, setSelected] = useState<T | null>(null);
  const [formState, setFormState] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initialState = useMemo(() => {
    return fields.reduce<Record<string, string>>((state, field) => {
      state[String(field.key)] = defaultValueForField(field);
      return state;
    }, {});
  }, [fields]);

  async function loadItems() {
    setLoading(true);
    setError(null);
    try {
      const data = await listItems<T>(endpoint);
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to load ${title}.`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setSelected(null);
    setFormState(initialState);
    loadItems();
  }, [endpoint, initialState]);

  function editItem(item: T) {
    setSelected(item);
    const nextState = fields.reduce<Record<string, string>>((state, field) => {
      const value = item[String(field.key)];
      state[String(field.key)] = value === undefined || value === null ? "" : String(value);
      return state;
    }, {});
    setFormState(nextState);
  }

  function resetForm() {
    setSelected(null);
    setFormState(initialState);
  }

  function buildPayload() {
    return fields.reduce<Record<string, unknown>>((payload, field) => {
      const key = String(field.key);
      const value = formState[key];
      if (field.type === "number") {
        payload[key] = value === "" ? null : Number(value);
      } else {
        payload[key] = value === "" ? null : value;
      }
      return payload;
    }, {});
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = buildPayload() as Partial<T>;
      if (selected) {
        await updateItem<T>(endpoint, selected.id, payload);
      } else {
        await createItem<T>(endpoint, payload);
      }
      resetForm();
      await loadItems();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to save ${title}.`);
    } finally {
      setSaving(false);
    }
  }

  async function removeItem(item: T) {
    setError(null);
    await deleteItem(endpoint, item.id);
    if (selected?.id === item.id) {
      resetForm();
    }
    await loadItems();
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Manage</p>
          <h1>{title}</h1>
        </div>
        <button className="secondaryButton" type="button" onClick={resetForm}>
          New
        </button>
      </header>

      {error && <div className="alert">{error}</div>}

      <div className="moduleGrid">
        <section className="panel">
          <h2>{selected ? `Edit ${title}` : `Create ${title}`}</h2>
          <form className="recordForm" onSubmit={handleSubmit}>
            {fields.map((field) => {
              const key = String(field.key);
              return (
                <label key={key}>
                  <span>
                    {field.label}
                    {field.required ? " *" : ""}
                  </span>
                  {field.type === "textarea" ? (
                    <textarea
                      value={formState[key] ?? ""}
                      required={field.required}
                      onChange={(event) => setFormState((current) => ({ ...current, [key]: event.target.value }))}
                    />
                  ) : (
                    <input
                      type={field.type ?? "text"}
                      value={formState[key] ?? ""}
                      required={field.required}
                      onChange={(event) => setFormState((current) => ({ ...current, [key]: event.target.value }))}
                    />
                  )}
                </label>
              );
            })}
            <div className="formActions">
              <button className="primaryButton" type="submit" disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </button>
              <button className="secondaryButton" type="button" onClick={resetForm}>
                Clear
              </button>
            </div>
          </form>
        </section>

        <section className="panel tablePanel">
          <h2>{title} Records</h2>
          {loading ? (
            <p>Loading records...</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    {tableColumns.map((column) => (
                      <th key={String(column)}>{humanize(String(column))}</th>
                    ))}
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      {tableColumns.map((column) => (
                        <td key={String(column)}>{formatCell(item[String(column)])}</td>
                      ))}
                      <td className="actionsCell">
                        <button className="linkButton" type="button" onClick={() => editItem(item)}>
                          Edit
                        </button>
                        <button className="dangerButton" type="button" onClick={() => removeItem(item)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 && (
                    <tr>
                      <td colSpan={tableColumns.length + 1}>No records found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function defaultValueForField<T>(field: FieldConfig<T>) {
  if (field.key === "state" || field.key === "geo_state") {
    return "FL";
  }
  if (field.key === "status") {
    return "active";
  }
  if (field.key === "exif_status") {
    return "pending";
  }
  return "";
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
}

function formatCell(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const text = String(value);
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

export default ModulePage;
