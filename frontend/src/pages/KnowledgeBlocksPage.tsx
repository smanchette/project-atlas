import { FormEvent, useEffect, useMemo, useState } from "react";

import { listItems, updateItem } from "../api";
import type { KnowledgeBlock } from "../types";

type KnowledgeFormState = Pick<
  KnowledgeBlock,
  "short_answer" | "long_answer" | "confidence_level" | "source_notes"
>;

const confidenceLevels: KnowledgeBlock["confidence_level"][] = ["High", "Medium", "Low"];

function KnowledgeBlocksPage() {
  const [blocks, setBlocks] = useState<KnowledgeBlock[]>([]);
  const [selected, setSelected] = useState<KnowledgeBlock | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [customerFilter, setCustomerFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [formState, setFormState] = useState<KnowledgeFormState>({
    short_answer: "",
    long_answer: "",
    confidence_level: "Medium",
    source_notes: ""
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadBlocks() {
    setLoading(true);
    setError(null);
    try {
      const data = await listItems<KnowledgeBlock>("/api/knowledge-blocks");
      setBlocks(data.sort((left, right) => left.sort_order - right.sort_order));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load knowledge blocks.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadBlocks();
  }, []);

  const categories = useMemo(
    () => Array.from(new Set(blocks.map((block) => block.category))).sort(),
    [blocks]
  );
  const customerTypes = useMemo(
    () => Array.from(new Set(blocks.map((block) => block.customer_type))).sort(),
    [blocks]
  );
  const statuses = useMemo(
    () => Array.from(new Set(blocks.map((block) => block.status))).sort(),
    [blocks]
  );

  const filteredBlocks = blocks.filter((block) => {
    return (
      (categoryFilter === "all" || block.category === categoryFilter) &&
      (customerFilter === "all" || block.customer_type === customerFilter) &&
      (statusFilter === "all" || block.status === statusFilter)
    );
  });

  function editBlock(block: KnowledgeBlock) {
    setSelected(block);
    setFormState({
      short_answer: block.short_answer,
      long_answer: block.long_answer,
      confidence_level: block.confidence_level,
      source_notes: block.source_notes ?? ""
    });
  }

  function clearSelection() {
    setSelected(null);
    setFormState({
      short_answer: "",
      long_answer: "",
      confidence_level: "Medium",
      source_notes: ""
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) {
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await updateItem<KnowledgeBlock>("/api/knowledge-blocks", selected.id, formState);
      clearSelection();
      await loadBlocks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update knowledge block.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Service Library</p>
          <h1>Knowledge Blocks</h1>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}

      <div className="knowledgeGrid">
        <section className="panel knowledgeEditor">
          <h2>{selected ? selected.title : "Knowledge Block Details"}</h2>
          {selected ? (
            <form className="recordForm" onSubmit={handleSubmit}>
              <div className="selectedQuestion">
                <span>Question</span>
                <p>{selected.question}</p>
              </div>
              <label>
                <span>Short Answer</span>
                <textarea
                  className="shortAnswerInput"
                  value={formState.short_answer}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, short_answer: event.target.value }))
                  }
                />
              </label>
              <label>
                <span>Long Answer</span>
                <textarea
                  className="longAnswerInput"
                  value={formState.long_answer}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, long_answer: event.target.value }))
                  }
                />
              </label>
              <label>
                <span>Confidence Level</span>
                <select
                  value={formState.confidence_level}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      confidence_level: event.target.value as KnowledgeBlock["confidence_level"]
                    }))
                  }
                >
                  {confidenceLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Source Notes</span>
                <textarea
                  value={formState.source_notes ?? ""}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, source_notes: event.target.value }))
                  }
                />
              </label>
              <div className="formActions">
                <button className="primaryButton" type="submit" disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </button>
                <button className="secondaryButton" type="button" onClick={clearSelection}>
                  Clear
                </button>
              </div>
            </form>
          ) : (
            <p>Select a knowledge block to edit its answers, confidence level, or source notes.</p>
          )}
        </section>

        <section className="panel tablePanel">
          <div className="panelHeader">
            <h2>Service Knowledge</h2>
            <span className="countBadge">{filteredBlocks.length} shown</span>
          </div>
          <div className="filterBar">
            <label>
              <span>Category</span>
              <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                <option value="all">All categories</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {humanize(category)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Customer Type</span>
              <select value={customerFilter} onChange={(event) => setCustomerFilter(event.target.value)}>
                <option value="all">All customer types</option>
                {customerTypes.map((customerType) => (
                  <option key={customerType} value={customerType}>
                    {humanize(customerType)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Status</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All statuses</option>
                {statuses.map((status) => (
                  <option key={status} value={status}>
                    {humanize(status)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {loading ? (
            <p>Loading knowledge blocks...</p>
          ) : (
            <div className="tableWrap">
              <table className="knowledgeTable">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Question</th>
                    <th>Category</th>
                    <th>Customer Type</th>
                    <th>Confidence</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBlocks.map((block) => (
                    <tr key={block.id}>
                      <td>{block.title}</td>
                      <td>{block.question}</td>
                      <td>{humanize(block.category)}</td>
                      <td>{humanize(block.customer_type)}</td>
                      <td>{block.confidence_level}</td>
                      <td>{block.status}</td>
                      <td>
                        <button className="linkButton" type="button" onClick={() => editBlock(block)}>
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredBlocks.length === 0 && (
                    <tr>
                      <td colSpan={7}>No knowledge blocks match these filters.</td>
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

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export default KnowledgeBlocksPage;
