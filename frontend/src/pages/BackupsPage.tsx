import { useEffect, useState } from "react";
import {
  Archive,
  Check,
  Clipboard,
  Code2,
  DatabaseBackup,
  FolderOpen,
  PackageCheck,
  RefreshCw
} from "lucide-react";

import { apiRequest, requestDataBackup, requestMediaBackup, requestProgramBackup } from "../api";

type BackupInfo = {
  file_name: string;
  created_at: string | null;
  table_counts: Record<string, number>;
  status: string;
  error?: string;
};

type DownloadResult = {
  files: string[];
};

const downloadsCommand = 'explorer "$env:USERPROFILE\\Downloads"';
const serverBackupsCommand = "explorer backend\\backups";
const gitCommands = `git status
git add .
git commit -m "Backup Atlas before next version"
git push`;

function BackupsPage() {
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportingMedia, setExportingMedia] = useState(false);
  const [exportingProgram, setExportingProgram] = useState(false);
  const [exportingFull, setExportingFull] = useState(false);
  const [downloadResult, setDownloadResult] = useState<DownloadResult | null>(null);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
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

  async function createFullBackup() {
    setExportingFull(true);
    clearFeedback();
    try {
      const [data, media, program] = await Promise.all([
        requestDataBackup<BackupInfo>(),
        requestMediaBackup(),
        requestProgramBackup()
      ]);
      downloadBlob(data.blob, data.fileName);
      await waitForNextDownload();
      downloadBlob(media.blob, media.fileName);
      await waitForNextDownload();
      downloadBlob(program.blob, program.fileName);
      setDownloadResult({ files: [data.fileName, media.fileName, program.fileName] });
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create the full Atlas backup.");
    } finally {
      setExportingFull(false);
    }
  }

  async function createBackup() {
    setExporting(true);
    clearFeedback();
    try {
      const data = await requestDataBackup<BackupInfo>();
      downloadBlob(data.blob, data.fileName);
      setDownloadResult({ files: [data.fileName] });
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create data backup.");
    } finally {
      setExporting(false);
    }
  }

  async function createMediaBackup() {
    setExportingMedia(true);
    clearFeedback();
    try {
      const media = await requestMediaBackup();
      downloadBlob(media.blob, media.fileName);
      setDownloadResult({ files: [media.fileName] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create media backup.");
    } finally {
      setExportingMedia(false);
    }
  }

  async function createProgramBackup() {
    setExportingProgram(true);
    clearFeedback();
    try {
      const program = await requestProgramBackup();
      downloadBlob(program.blob, program.fileName);
      setDownloadResult({ files: [program.fileName] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create program backup.");
    } finally {
      setExportingProgram(false);
    }
  }

  function clearFeedback() {
    setDownloadResult(null);
    setMessage(null);
    setError(null);
  }

  async function copyCommand(command: string) {
    try {
      await copyText(command);
      setCopiedCommand(command);
      setMessage("Command copied.");
      setError(null);
      window.setTimeout(() => setCopiedCommand(null), 1800);
    } catch {
      setError("Unable to copy the command. Select the command text and copy it manually.");
    }
  }

  return (
    <section className="page backupsPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Data Protection</p>
          <h1>Backup Center</h1>
        </div>
      </header>

      <section className="panel fullBackupPanel">
        <div className="fullBackupIntro">
          <PackageCheck size={30} aria-hidden="true" />
          <div>
            <h2>Full Atlas Backup</h2>
            <p>Create fresh data, media, and program backups and download all three files separately.</p>
          </div>
        </div>
        <button
          className="primaryButton buttonWithIcon fullBackupButton"
          type="button"
          onClick={createFullBackup}
          disabled={exportingFull || exporting || exportingMedia || exportingProgram}
        >
          {exportingFull ? <RefreshCw size={18} aria-hidden="true" /> : <PackageCheck size={18} aria-hidden="true" />}
          {exportingFull ? "Creating Full Backup..." : "Create Full Atlas Backup"}
        </button>
      </section>

      <div className="backupTypeGrid">
        <div>
          <strong>Data Backup</strong>
          <span>Saves Atlas records, generated pages, QA results, notes, revisions, and approval history.</span>
        </div>
        <div>
          <strong>Media Backup</strong>
          <span>Saves uploaded and preview image files.</span>
        </div>
        <div>
          <strong>Program Backup</strong>
          <span>Saves app code and rebuild configuration, excluding media, backups, caches, dependencies, Git data, and secrets.</span>
        </div>
      </div>

      {downloadResult && (
        <div className="successAlert backupDownloadSuccess">
          <Check size={18} aria-hidden="true" />
          <div>
            <strong>Backup files were downloaded to your browser Downloads folder.</strong>
            <ul>
              {downloadResult.files.map((file) => <li key={file}>{file}</li>)}
            </ul>
          </div>
        </div>
      )}
      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <section className="panel separateBackupsPanel">
        <div className="panelHeader">
          <div>
            <h2>Advanced / Separate Backups</h2>
            <p>Create only the file you need.</p>
          </div>
        </div>
        <div className="separateBackupActions">
          <button
            className="secondaryButton buttonWithIcon"
            type="button"
            onClick={createBackup}
            disabled={exporting || exportingFull}
          >
            {exporting ? <RefreshCw size={17} aria-hidden="true" /> : <DatabaseBackup size={17} aria-hidden="true" />}
            {exporting ? "Creating..." : "Create Data Backup"}
          </button>
          <button
            className="secondaryButton buttonWithIcon"
            type="button"
            onClick={createMediaBackup}
            disabled={exportingMedia || exportingFull}
          >
            {exportingMedia ? <RefreshCw size={17} aria-hidden="true" /> : <Archive size={17} aria-hidden="true" />}
            {exportingMedia ? "Creating..." : "Create Media Backup"}
          </button>
          <button
            className="secondaryButton buttonWithIcon"
            type="button"
            onClick={createProgramBackup}
            disabled={exportingProgram || exportingFull}
          >
            {exportingProgram ? <RefreshCw size={17} aria-hidden="true" /> : <Code2 size={17} aria-hidden="true" />}
            {exportingProgram ? "Creating..." : "Create Program Backup"}
          </button>
        </div>
      </section>

      <div className="backupHelpGrid">
        <section className="panel backupHelpPanel">
          <div className="backupHelpHeading">
            <FolderOpen size={21} aria-hidden="true" />
            <h2>Where are my backups?</h2>
          </div>
          <p>Browser downloads go to your Windows Downloads folder.</p>
          <CopyCommand
            command={downloadsCommand}
            copied={copiedCommand === downloadsCommand}
            onCopy={copyCommand}
          />
          <p>Command-line data exports remain in <code>backend/backups</code>.</p>
          <CopyCommand
            command={serverBackupsCommand}
            copied={copiedCommand === serverBackupsCommand}
            onCopy={copyCommand}
          />
        </section>

        <section className="panel backupHelpPanel">
          <div className="backupHelpHeading">
            <Code2 size={21} aria-hidden="true" />
            <h2>Program/code backup</h2>
          </div>
          <p>GitHub is still the best version-history backup for code.</p>
          <p>Before major versions, commit and push the code to GitHub.</p>
          <CopyCommand
            command={gitCommands}
            copied={copiedCommand === gitCommands}
            onCopy={copyCommand}
            multiline
          />
          <small>Atlas will not run these Git commands automatically.</small>
        </section>
      </div>

      <section className="panel tablePanel">
        <div className="panelHeader">
          <h2>Available Data Backups</h2>
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
                          <span key={table}>{humanize(table)}: <strong>{count}</strong></span>
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
                  <tr><td colSpan={4}>No backup files found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel restorePanel">
        <h2>Restore From Backup</h2>
        <p>Restore remains CLI-only and uses non-destructive upserts.</p>
        <code className="commandBlock">
          docker compose exec backend python -m app.db.backup restore backend/backups/&lt;filename&gt;.json
        </code>
      </section>
    </section>
  );
}

function CopyCommand({
  command,
  copied,
  onCopy,
  multiline = false
}: {
  command: string;
  copied: boolean;
  onCopy: (command: string) => Promise<void>;
  multiline?: boolean;
}) {
  return (
    <div className={`copyCommand ${multiline ? "multiline" : ""}`}>
      <code>{command}</code>
      <button
        type="button"
        className="iconButton"
        onClick={() => onCopy(command)}
        title={copied ? "Copied" : "Copy command"}
        aria-label={copied ? "Command copied" : "Copy command"}
      >
        {copied ? <Check size={16} aria-hidden="true" /> : <Clipboard size={16} aria-hidden="true" />}
      </button>
    </div>
  );
}

function downloadBlob(blob: Blob, fileName: string) {
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
}

function waitForNextDownload() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, 250));
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    return;
  } catch {
    const textArea = document.createElement("textarea");
    textArea.value = value;
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.select();
    const copied = document.execCommand("copy");
    textArea.remove();
    if (!copied) throw new Error("Copy command failed.");
  }
}

function formatTimestamp(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export default BackupsPage;
