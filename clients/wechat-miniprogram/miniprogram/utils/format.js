const COLUMN_LABELS = {
  line: "线路",
  station: "车站",
  direction: "方向",
  time: "时间",
  entries: "进站量",
  exits: "出站量",
  transfers: "换乘量",
  net_inflow: "净流入",
  timestamp: "时间",
  line_id: "线路",
  station_id: "车站",
  scheme_id: "方案"
}

const DIRECTION_LABELS = { up: "上行", down: "下行", na: "不区分" }

function formatNumber(value) {
  const number = Number(value || 0)
  return String(number).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function formatValue(column, value) {
  if (column === "direction") return DIRECTION_LABELS[value] || value
  if (["entries", "exits", "transfers", "net_inflow"].includes(column)) {
    return formatNumber(value)
  }
  if ((column === "time" || column === "timestamp") && typeof value === "string") {
    return value.replace("T", " ").replace(/\+08:00$/, "")
  }
  return value === null || value === undefined ? "—" : String(value)
}

function columnsForResult(dimensions, metric) {
  return [...dimensions, metric].map((id) => ({ id, label: COLUMN_LABELS[id] || id }))
}

function displayRows(rows, columns) {
  return rows.map((row, index) => ({
    id: String(index),
    cells: columns.map((column) => formatValue(column.id, row[column.id]))
  }))
}

function chartBars(rows, labelColumn, metric) {
  if (!labelColumn || !rows.length) return []
  const maximum = Math.max(...rows.map((row) => Math.abs(Number(row[metric] || 0))), 1)
  return rows.slice(0, 8).map((row, index) => ({
    id: String(index),
    label: formatValue(labelColumn, row[labelColumn]),
    value: formatNumber(row[metric]),
    width: Math.max(4, Math.round((Math.abs(Number(row[metric] || 0)) / maximum) * 100))
  }))
}

module.exports = {
  COLUMN_LABELS,
  DIRECTION_LABELS,
  chartBars,
  columnsForResult,
  displayRows,
  formatNumber,
  formatValue
}
