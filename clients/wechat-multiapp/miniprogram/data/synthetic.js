const METRICS = [
  {
    id: "entries",
    source_fields: ["entries"],
    aggregation: "sum",
    unit: "passengers",
    dimensions: ["line", "station", "direction", "time"]
  },
  {
    id: "exits",
    source_fields: ["exits"],
    aggregation: "sum",
    unit: "passengers",
    dimensions: ["line", "station", "direction", "time"]
  },
  {
    id: "transfers",
    source_fields: ["transfers"],
    aggregation: "sum",
    unit: "passengers",
    dimensions: ["line", "station", "time"]
  },
  {
    id: "net_inflow",
    source_fields: ["entries", "exits"],
    aggregation: "sum_difference",
    unit: "passengers",
    dimensions: ["line", "station", "direction", "time"]
  }
]

const ROWS = [
  { timestamp: "2026-07-20T08:00:00+08:00", line_id: "L-A", station_id: "S-ALPHA", direction: "up", entries: 120, exits: 40, transfers: 10 },
  { timestamp: "2026-07-20T08:00:00+08:00", line_id: "L-A", station_id: "S-ALPHA", direction: "down", entries: 80, exits: 60, transfers: 8 },
  { timestamp: "2026-07-20T08:00:00+08:00", line_id: "L-A", station_id: "S-BETA", direction: "up", entries: 70, exits: 90, transfers: 20 },
  { timestamp: "2026-07-20T08:00:00+08:00", line_id: "L-A", station_id: "S-BETA", direction: "down", entries: 55, exits: 75, transfers: 18 },
  { timestamp: "2026-07-20T09:00:00+08:00", line_id: "L-A", station_id: "S-ALPHA", direction: "up", entries: 100, exits: 65, transfers: 9 },
  { timestamp: "2026-07-20T09:00:00+08:00", line_id: "L-A", station_id: "S-ALPHA", direction: "down", entries: 75, exits: 70, transfers: 7 }
]

module.exports = { METRICS, ROWS }
