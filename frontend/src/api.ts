const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: isFormData
      ? options?.headers
      : {
          "Content-Type": "application/json",
          ...(options?.headers ?? {})
        },
    ...options
  });

  if (!response.ok) {
    const responseText = await response.text();
    let detail: unknown = responseText;
    try {
      const payload = JSON.parse(responseText) as { detail?: unknown };
      detail = payload.detail ?? payload;
    } catch {
      // Keep plain response text when the server did not return JSON.
    }
    const message =
      typeof detail === "string"
        ? detail
        : isMessageDetail(detail)
          ? detail.message
          : responseText || `Request failed with ${response.status}`;
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function isMessageDetail(value: unknown): value is { message: string } {
  return Boolean(
    value &&
    typeof value === "object" &&
    "message" in value &&
    typeof (value as { message?: unknown }).message === "string"
  );
}

export async function requestMediaBackup(): Promise<{ blob: Blob; fileName: string }> {
  return requestZipBackup("/api/backups/media", "atlas-media-backup.zip");
}

export async function requestProgramBackup(): Promise<{ blob: Blob; fileName: string }> {
  return requestZipBackup("/api/backups/program", "atlas-program-backup.zip");
}

async function requestZipBackup(
  path: string,
  fallbackFileName: string
): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "POST" });
  if (!response.ok) {
    let message = await response.text();
    try {
      const payload = JSON.parse(message) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Keep the response text when the server did not return JSON.
    }
    throw new Error(message || `Request failed with ${response.status}`);
  }

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const fileNameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    fileName: fileNameMatch?.[1] ?? fallbackFileName
  };
}

export async function requestDataBackup<T>(): Promise<{ backup: T; blob: Blob; fileName: string }> {
  const backup = await apiRequest<T>("/api/backups/export", { method: "POST" });
  const fileName = (backup as { file_name?: string }).file_name;
  if (!fileName) {
    throw new Error("Atlas did not return a data backup filename.");
  }
  const response = await fetch(`${API_BASE_URL}/api/backups/data/${encodeURIComponent(fileName)}`);
  if (!response.ok) {
    throw new Error((await response.text()) || `Request failed with ${response.status}`);
  }
  return { backup, blob: await response.blob(), fileName };
}

export function requestPageExport(pageId: number): Promise<{ blob: Blob; fileName: string }> {
  return requestFileDownload(
    `/api/generated-pages/${pageId}/export-package/download`,
    { method: "GET" },
    `atlas-page-export-${pageId}.json`
  );
}

export function requestBulkPageExport(pageIds: number[]): Promise<{ blob: Blob; fileName: string }> {
  return requestFileDownload(
    "/api/generated-pages/export/bulk",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_ids: pageIds })
    },
    "atlas-page-exports.zip"
  );
}

async function requestFileDownload(
  path: string,
  options: RequestInit,
  fallbackFileName: string
): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new Error((await response.text()) || `Request failed with ${response.status}`);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const fileNameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    fileName: fileNameMatch?.[1] ?? fallbackFileName
  };
}

export function listItems<T>(endpoint: string): Promise<T[]> {
  return apiRequest<T[]>(endpoint);
}

export function createItem<T>(endpoint: string, payload: Partial<T>): Promise<T> {
  return apiRequest<T>(endpoint, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateItem<T>(endpoint: string, id: number, payload: Partial<T>): Promise<T> {
  return apiRequest<T>(`${endpoint}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteItem(endpoint: string, id: number): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`${endpoint}/${id}`, {
    method: "DELETE"
  });
}

export function uploadMedia<T>(payload: FormData): Promise<T> {
  return apiRequest<T>("/api/media/upload", {
    method: "POST",
    body: payload
  });
}
