import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useTokenColors } from '@/hooks/use-token-colors'
import { platformMeta } from '@/components/media/platform-badge'

const CHART_TOKENS = {
  grid: '--border',
  axis: '--muted-foreground',
  surface: '--popover',
  text: '--popover-foreground',
  brand: '--primary',
  accent: '--brand-to',
  success: '--success',
  destructive: '--destructive',
  warning: '--warning',
  muted: '--muted-foreground',
} as const

type ChartColors = Record<keyof typeof CHART_TOKENS, string>

function useChartColors(): ChartColors {
  return useTokenColors(CHART_TOKENS)
}

function tooltipStyles(colors: ChartColors) {
  return {
    contentStyle: {
      background: colors.surface,
      border: `1px solid ${colors.grid}`,
      borderRadius: '0.5rem',
      fontSize: '0.8125rem',
      color: colors.text,
      boxShadow: '0 4px 16px -4px rgb(0 0 0 / 0.15)',
    },
    labelStyle: { color: colors.text, fontWeight: 500 },
    itemStyle: { color: colors.text },
  }
}

/** Short axis label from an ISO date: "Mar 4". */
function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/* -------------------------------------------------------------------------- */
/* Daily downloads                                                             */
/* -------------------------------------------------------------------------- */

export function DailyDownloadsChart({
  data,
}: {
  data: { date: string; total: number; successful: number; failed: number }[]
}) {
  const colors = useChartColors()
  const tooltip = tooltipStyles(colors)

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={{ fill: colors.axis, fontSize: 11 }}
          stroke={colors.grid}
          interval="preserveStartEnd"
        />
        <YAxis
          allowDecimals={false}
          tick={{ fill: colors.axis, fontSize: 11 }}
          stroke={colors.grid}
          width={44}
        />
        <Tooltip labelFormatter={shortDate} {...tooltip} />
        <Legend
          wrapperStyle={{ fontSize: '0.75rem', color: colors.axis, paddingTop: 8 }}
          iconType="plainline"
        />
        <Line
          type="monotone"
          dataKey="successful"
          name="Successful"
          stroke={colors.success}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="failed"
          name="Failed"
          stroke={colors.destructive}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/* -------------------------------------------------------------------------- */
/* Platform distribution                                                       */
/* -------------------------------------------------------------------------- */

export function PlatformBarChart({
  data,
}: {
  data: { platform: string; count: number }[]
}) {
  const colors = useChartColors()
  const tooltip = tooltipStyles(colors)
  const rows = data.map((row) => ({ ...row, label: platformMeta(row.platform).label }))

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 34 + 24)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          allowDecimals={false}
          tick={{ fill: colors.axis, fontSize: 11 }}
          stroke={colors.grid}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={92}
          tick={{ fill: colors.axis, fontSize: 11 }}
          stroke={colors.grid}
        />
        <Tooltip {...tooltip} />
        <Bar dataKey="count" name="Downloads" fill={colors.brand} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/* -------------------------------------------------------------------------- */
/* Status breakdown                                                            */
/* -------------------------------------------------------------------------- */

export function StatusPieChart({ data }: { data: { status: string; count: number }[] }) {
  const colors = useChartColors()
  const tooltip = tooltipStyles(colors)

  const sliceColor = (status: string): string => {
    if (status === 'ready') return colors.success
    if (status === 'failed') return colors.destructive
    if (status === 'expired' || status === 'cancelled') return colors.muted
    return colors.brand
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          dataKey="count"
          nameKey="status"
          innerRadius={52}
          outerRadius={82}
          paddingAngle={2}
          strokeWidth={0}
        >
          {data.map((slice) => (
            <Cell key={slice.status} fill={sliceColor(slice.status)} />
          ))}
        </Pie>
        <Tooltip {...tooltip} />
        <Legend
          wrapperStyle={{ fontSize: '0.75rem', color: colors.axis }}
          formatter={(value) => String(value)}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}
