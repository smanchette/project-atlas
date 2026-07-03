import { useEffect, useState } from "react";
import { Archive, DatabaseBackup, RefreshCw } from "lucide-react";

import { apiRequest, requestMediaBackup } from "../api";

type BackupInfo = {
  file_name: string;
  created_at: string | null;
  table_counts: Record<string, number>;
  status: string;
  error?: string;
};

function BackupsPage() {
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportingMedia, setExportingMedia] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadBackups() {
    setLoading(true);
    setError(null);
    try {
      setBackups(await apiRequest<BackupInfo[]>("/api/backups"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load backups.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadBackups();
  }, []);

  async function createBackup() {
    setExporting(true);
    setMessage(null);
    setError(null);
    try {
      const backup = await apiRequest<BackupInfo>("/api/backups/export", { method: "POST" });
      setMessage(`${backup.file_name} created successfully.`);
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create backup.");
    } finally {
      setExporting(false);
    }
  }

  async function createMediaBackup() {
    setExportingMedia(true);
    setMessage(null);
    setError(null);
    try {
      const backup = await requestMediaBackup();
      const downloadUrl = URL.createObjectURL(backup.blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = backup.fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
      setMessage(`${backup.fileName} downloaded successfully.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create media backup.");
    } finally {
      setExportingMedia(false);
    }
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Data Protection</p>
          <h1>Backups</h1>
        </div>
        <div className="headerActions">
          <button className="primaryButton buttonWithIcon" type="button" onClick={createBackup} disabled={exporting}>
            {exporting ? <RefreshCw size={17} aria-hidden="true" /> : <DatabaseBackup size={17} aria-hidden="true" />}
            {exporting ? "Creating..." : "Create Data Backup"}
          </button>
          <button
            className="secondaryButton buttonWithIcon"
            type="button"
            onClick={createMediaBackup}
            disabled={exportingMedia}
          >
            {exportingMedia ? <RefreshCw size={17} aria-hidden="true" /> : <Archive size={17} aria-hidden="true" />}
            {exportingMedia ? "Creating..." : "Create Media Backup"}
          </button>
        </div>
      </header>

      <p className="helperText">
        Data backups save Atlas records. Media backups save uploaded and preview image files.
      </p>

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <section className="panel tablePanel">
        <div className="panelHeader">
          <h2>Available Backups</h2>
          <span className="countBadge">{backups.length} files</span>
        </div>
        {loading ? (
          <p>Loading backups...</p>
        ) : (
          <div className="tableWrap">
            <table className="backupTable">
              <thead>
                <tr>
                  <th>File Name</th>
                  <th>Created</th>
                  <th>Table Counts</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {backups.map((backup) => (
                  <tr key={backup.file_name}>
                    <td>{backup.file_name}</td>
                    <td>{formatTimestamp(backup.created_at)}</td>
                    <td>
                      <div className="backupCounts">
                        {Object.entries(backup.table_counts).map(([table, count]) => (
                          <span key={table}>
                            {humanize(table)}: <strong>{count}</strong>
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <span className={backup.status === "ready" ? "statusReady" : "statusInvalid"}>
                        {humanize(backup.status)}
                      </span>
                      {backup.error && <div className="cellError">{backup.error}</div>}
                    </td>
                  </tr>
                ))}
                {backups.length === 0 && (
                  <tr>
                    <td colSpan={4}>No backup files found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel restorePanel">
        <h2>Restore From Backup</h2>
        <p>Restore is CLI-only in v0.4 and uses non-destructive upserts.</p>
        <code className="commandBlock">
          docker compose exec backend python -m app.db.backup restore backend/backups/&lt;filename&gt;.json
        </code>
      </section>
    </section>
  );
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export default BackupsPage;
