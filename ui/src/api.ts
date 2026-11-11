import Keycloak from "keycloak-js";

export const kc = new Keycloak({ url: "http://localhost:8080", realm: "rgpf", clientId: "rgpf-ui" });

export async function login(): Promise<void> {
  await kc.init({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false });
  setInterval(() => kc.updateToken(60).catch(() => kc.login()), 30000);
}

export function hasRole(...roles: string[]): boolean {
  const mine = (kc.tokenParsed?.realm_access?.roles ?? []) as string[];
  return mine.includes("admin") || roles.some((r) => mine.includes(r));
}

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${kc.token}` } });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return path.endsWith(".svg") ? ((await r.text()) as unknown as T) : r.json();
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${kc.token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export function liveSocket(onData: (rows: Live[]) => void): WebSocket {
  const ws = new WebSocket(`ws://${location.host}/api/v1/ws/live?token=${kc.token}`);
  ws.onmessage = (e) => onData(JSON.parse(e.data));
  return ws;
}

export interface Live { tag: string; value: number | null; quality: string; ts: string }
export interface TagDef { tag: string; class: string; desc: string; equipment: string | null; range: [number, number]; nominal: number; unit: string }
export interface GraphNode { id: string; kind: string; name: string; props: Record<string, unknown> }
export interface AssetContext {
  node: GraphNode & { path: string | null };
  outgoing: (GraphNode & { rel: string })[];
  incoming: { rel: string; id: string; kind: string; name: string }[];
  live: Live[];
  work_orders?: Record<string, string | number | null>[];
}
