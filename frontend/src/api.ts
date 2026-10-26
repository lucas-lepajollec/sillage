export const ACCESS_KEY = "sillage.access-key";
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const key = sessionStorage.getItem(ACCESS_KEY);
  const response = await fetch(`/api${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(key ? { "X-Access-Key": key } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("sillage:unauthorized"));
    const error = await response
      .json()
      .catch(() => ({ detail: `Erreur HTTP ${response.status}` }));
    const detail =
      typeof error.detail === "string"
        ? error.detail
        : Array.isArray(error.detail)
          ? error.detail.map((e: { msg: string }) => e.msg).join(" · ")
          : "La requête a échoué.";
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}
export async function downloadJob(id: string, name: string) {
  const key = sessionStorage.getItem(ACCESS_KEY);
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/download`, {
    headers: key ? { "X-Access-Key": key } : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Le téléchargement a échoué.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const filename = response.headers
    .get("Content-Disposition")
    ?.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i)?.[1];
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename ? decodeURIComponent(filename) : name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
export const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Une erreur inattendue est survenue.";
