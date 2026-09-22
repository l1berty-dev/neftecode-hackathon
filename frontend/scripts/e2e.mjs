const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8080";
const response = await fetch(`${base}/api/v1/modelled-presets`);
if (!response.ok) throw new Error(`modelled presets returned ${response.status}`);
const { items } = await response.json();
if (!Array.isArray(items) || items.length !== 5) {
  throw new Error(`expected 5 presets, received ${items?.length ?? "invalid payload"}`);
}
for (const preset of items) {
  const run = await fetch(`${base}/api/v1/modelled-runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(preset.request),
  });
  if (!run.ok) throw new Error(`${preset.preset_id} returned ${run.status}`);
  const payload = await run.json();
  if (payload.result.status !== preset.expected_status) {
    throw new Error(`${preset.preset_id}: expected ${preset.expected_status}, got ${payload.result.status}`);
  }
}
console.log("Five modelled presets passed through the live HTTP API.");
