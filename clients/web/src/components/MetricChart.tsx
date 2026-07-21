import { BarChart, LineChart } from "echarts/charts"
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components"
import * as echarts from "echarts/core"
import { CanvasRenderer } from "echarts/renderers"
import { useEffect, useRef } from "react"

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export type ChartProps = {
  labels: string[]
  values: number[]
  kind?: "bar" | "line"
  color?: string
  height?: number
  name?: string
}

export function MetricChart({
  labels,
  values,
  kind = "bar",
  color = "#22d3ee",
  height = 260,
  name = "客流",
}: ChartProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption({
      animationDuration: 700,
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0c192a",
        borderColor: "#24364d",
        textStyle: { color: "#e2e8f0" },
      },
      grid: { left: 18, right: 12, top: 22, bottom: 16, containLabel: true },
      xAxis: {
        type: "category",
        data: labels,
        axisLine: { lineStyle: { color: "#2a3b51" } },
        axisLabel: { color: "#8292a8", hideOverlap: true },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(148,163,184,.10)" } },
        axisLabel: { color: "#8292a8" },
      },
      series: [
        {
          name,
          type: kind,
          data: values,
          smooth: kind === "line",
          symbol: "circle",
          symbolSize: 7,
          lineStyle: { width: 3, color },
          itemStyle: { color, borderRadius: kind === "bar" ? [6, 6, 0, 0] : 0 },
          areaStyle:
            kind === "line"
              ? {
                  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: `${color}55` },
                    { offset: 1, color: `${color}00` },
                  ]),
                }
              : undefined,
        },
      ],
    })
    let resizeFrame = 0
    const resize = () => {
      cancelAnimationFrame(resizeFrame)
      resizeFrame = requestAnimationFrame(() => {
        if (ref.current) chart.resize({ width: ref.current.clientWidth })
      })
    }
    window.addEventListener("resize", resize)
    const observer = new ResizeObserver(resize)
    observer.observe(ref.current)
    return () => {
      cancelAnimationFrame(resizeFrame)
      observer.disconnect()
      window.removeEventListener("resize", resize)
      chart.dispose()
    }
  }, [color, kind, labels, name, values])

  return (
    <div
      ref={ref}
      className="w-full min-w-0 overflow-hidden"
      style={{ height }}
      role="img"
      aria-label={`${name}图表`}
    />
  )
}
