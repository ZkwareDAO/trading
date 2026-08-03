"""HTML 模板"""

CHART_HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <script>{plotly_js}</script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        h1, h2 {{ color: #333; margin-bottom: 10px; }}
        .stats {{ background: #e7f3ff; padding: 15px; border-radius: 8px; margin: 10px 0; }}
        .info {{ background: #fff3cd; padding: 10px; border-radius: 8px; margin: 10px 0; font-size: 14px; }}
        .indicator-panel {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 10px 0; }}
        .indicator-panel label {{ margin-right: 15px; cursor: pointer; }}
        .indicator-panel input[type="checkbox"] {{ margin-right: 5px; }}
        .apply-btn {{ background: #4CAF50; color: white; padding: 8px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin-left: 20px; }}
        .apply-btn:hover {{ background: #45a049; }}
        #chartContainer {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; min-height: 600px; }}
        .table-container {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .data-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
        .data-table th, .data-table td {{ border: 1px solid #ddd; padding: 6px; text-align: right; }}
        .data-table th {{ background-color: #4CAF50; color: white; position: sticky; top: 0; }}
        .data-table tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .data-table tr:hover {{ background-color: #ddd; }}
        .positive {{ color: green; font-weight: bold; }}
        .negative {{ color: red; font-weight: bold; }}
        .bullish {{ background-color: #d4edda; }}
        .bearish {{ background-color: #f8d7da; }}
        .adx-trend {{ background-color: #e2d5f1; }}
        .entry-long {{ background-color: #cce5ff !important; border: 3px solid #0066cc; }}
        .entry-short {{ background-color: #ffe6cc !important; border: 3px solid #ff6600; }}
        .exit-profit {{ background-color: #d4edda !important; border: 3px solid green; }}
        .exit-loss {{ background-color: #f8d7da !important; border: 3px solid red; }}
        .entry-col {{ font-weight: bold; color: #0066cc; text-align: left; background: #e6f2ff; }}
        .exit-col {{ font-weight: bold; text-align: left; }}
        .filter-input {{ margin: 10px 0; padding: 10px; width: 400px; font-size: 14px; border: 1px solid #ddd; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="stats">
        <strong>Total K-lines:</strong> {total_klines} |
        <strong>LONG:</strong> {long_cnt} |
        <strong>SHORT:</strong> {short_cnt}
    </div>
    <div class="indicator-panel">
        <strong>📊 技术指标：</strong>
        <label><input type="checkbox" id="ind_OBV"> OBV</label>
        <label><input type="checkbox" id="ind_ADX"> ADX</label>
        <label><input type="checkbox" id="ind_ATR"> ATR</label>
        <label><input type="checkbox" id="ind_FVG"> FVG</label>
        <label><input type="checkbox" id="ind_RSI"> RSI</label>
        <label><input type="checkbox" id="ind_MACD"> MACD</label>
        <label><input type="checkbox" id="ind_BB"> 布林带</label>
        <label><input type="checkbox" id="ind_Swing"> Swing</label>
        <button class="apply-btn" onclick="applyIndicators()">应用</button>
    </div>
    <div class="info">
        📌 显示 <input type="number" id="displayCountInput" value="{display_count}" min="{min_count}" max="{max_count}" step="10" style="width: 60px; padding: 2px 5px; font-size: 14px; border: 1px solid #ccc; border-radius: 3px;"> 根 K线
        <label><input type="checkbox" id="autoAdapt" checked style="margin-left: 20px;"> 自动适配屏幕</label>
        <span id="adaptHint" style="margin-left: 10px; color: #666; font-size: 12px;"></span>
    </div>
    <h2>Interactive Chart (Drag to Load More)</h2>
    <div id="chartContainer"></div>
    <h2>Data Table (Current View)</h2>
    <div class="table-container">
        <input type="text" id="filterInput" class="filter-input" placeholder="Filter: LONG, SHORT, profit, loss, date...">
        <div style="overflow-x:auto; max-height: 600px; margin-top: 10px;">
            <table id="dataTable" class="data-table">
                <thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Price MA(20)</th><th>OBV</th><th>OBV MA(20)</th><th>OBV Signal</th><th>ADX</th><th>ADX Signal</th><th>Volume</th><th>Entry</th><th>Exit</th></tr></thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
    </div>
<script>
const allData = {data_json};
const TOTAL_KLINES = allData.timestamps.length;
let currentStartIndex = 0;
let enabledIndicators = {enabled_indicators_json};
const ADAPTIVE_CONFIG = {adaptive_config_json};
const DISPLAY_LIMITS = {{ min: {min_count}, max: {max_count} }};
const COLORS = {colors_json};

// 初始化指标复选框状态
function initIndicatorCheckboxes() {{
    const available = {available_indicators_json};
    available.forEach(name => {{
        const checkbox = document.getElementById('ind_' + name);
        if (checkbox) checkbox.checked = enabledIndicators.includes(name);
    }});
}}

function getAutoDisplayCount() {{
    const width = window.innerWidth;
    for (const key in ADAPTIVE_CONFIG) if (width < ADAPTIVE_CONFIG[key].max_width) return ADAPTIVE_CONFIG[key].count;
    return ADAPTIVE_CONFIG.xlarge.count;
}}

let DISPLAY_COUNT = getAutoDisplayCount();
let isRelayouting = false;

function updateAdaptHint() {{
    const hint = document.getElementById('adaptHint');
    const autoCheckbox = document.getElementById('autoAdapt');
    hint.textContent = autoCheckbox.checked ? '(当前适配: ' + getAutoDisplayCount() + ' 根)' : '(自定义设置)';
}}

function applyIndicators() {{
    const available = {available_indicators_json};
    enabledIndicators = available.filter(name => {{
        const checkbox = document.getElementById('ind_' + name);
        return checkbox && checkbox.checked;
    }});
    renderChart(currentStartIndex, true);
}}

document.getElementById('autoAdapt').addEventListener('change', function() {{
    if (this.checked) {{
        DISPLAY_COUNT = getAutoDisplayCount();
        document.getElementById('displayCountInput').value = DISPLAY_COUNT;
        renderChart(Math.min(currentStartIndex, Math.max(0, TOTAL_KLINES - DISPLAY_COUNT)), true);
    }}
    updateAdaptHint();
}});

document.getElementById('displayCountInput').addEventListener('change', function() {{
    let value = parseInt(this.value) || {default_count};
    value = Math.max(DISPLAY_LIMITS.min, Math.min(DISPLAY_LIMITS.max, value));
    this.value = value;
    DISPLAY_COUNT = value;
    document.getElementById('autoAdapt').checked = false;
    renderChart(Math.min(currentStartIndex, Math.max(0, TOTAL_KLINES - DISPLAY_COUNT)), true);
    updateAdaptHint();
}});

function getCurrentData(startIdx) {{
    startIdx = Math.max(0, Math.min(startIdx, TOTAL_KLINES - DISPLAY_COUNT));
    const endIdx = Math.min(startIdx + DISPLAY_COUNT, TOTAL_KLINES);
    const slice = {{
        timestamps: allData.timestamps.slice(startIdx, endIdx),
        open: allData.open.slice(startIdx, endIdx),
        high: allData.high.slice(startIdx, endIdx),
        low: allData.low.slice(startIdx, endIdx),
        close: allData.close.slice(startIdx, endIdx),
        volume: allData.volume.slice(startIdx, endIdx),
        price_ma: allData.price_ma.slice(startIdx, endIdx)
    }};
    const startTime = slice.timestamps[0];
    const endTime = slice.timestamps[slice.timestamps.length - 1];
    slice.trades = allData.trades.filter(t => t.entry_time >= startTime && t.entry_time <= endTime);

    // 添加启用的指标数据
    if (enabledIndicators.includes('OBV')) {{
        slice.obv = allData.obv.slice(startIdx, endIdx);
        slice.obv_ma = allData.obv_ma.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('ADX')) {{
        slice.adx = allData.adx.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('ATR')) {{
        slice.atr = allData.atr.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('RSI')) {{
        slice.rsi = allData.rsi.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('MACD')) {{
        slice.macd = allData.macd.slice(startIdx, endIdx);
        slice.macd_signal = allData.macd_signal.slice(startIdx, endIdx);
        slice.macd_hist = allData.macd_hist.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('BB')) {{
        slice.bb_upper = allData.bb_upper.slice(startIdx, endIdx);
        slice.bb_middle = allData.bb_middle.slice(startIdx, endIdx);
        slice.bb_lower = allData.bb_lower.slice(startIdx, endIdx);
    }}
    if (enabledIndicators.includes('FVG')) {{
        // 只显示当前可视范围内的 FVG（FVG 开始时间在当前范围内）
        slice.fvg_bullish = (allData.fvg_bullish || []).filter(fvg => fvg.start_time >= startTime && fvg.start_time <= endTime);
        slice.fvg_bearish = (allData.fvg_bearish || []).filter(fvg => fvg.start_time >= startTime && fvg.start_time <= endTime);
    }}
    if (enabledIndicators.includes('Swing')) {{
        // 只显示当前可视范围内的 Swing Points
        slice.swing_highs = (allData.swing_highs || []).filter(s => s.time >= startTime && s.time <= endTime);
        slice.swing_lows = (allData.swing_lows || []).filter(s => s.time >= startTime && s.time <= endTime);
    }}

    return {{ slice, startIdx, endIdx }};
}}

function getYAxisDomains() {{
    // 子图指标（需要独立 Y 轴）
    const subPlotIndicators = ['OBV', 'ADX', 'ATR', 'RSI', 'MACD'];
    const indicatorCount = enabledIndicators.filter(i => subPlotIndicators.includes(i)).length;

    // 动态高度分配（单位：px）
    // 基础总高度 500px，每个子图指标增加 120px
    const baseHeight = 500;
    const indicatorUnitHeight = 120;
    const totalHeight = baseHeight + indicatorCount * indicatorUnitHeight;

    // 主图占总高度的比例：基础 60%，但有最小绝对高度保证
    // 无子图指标：主图占 60%
    // 有子图指标：主图占 max(40%, 300px/totalHeight)
    let mainChartRatio;
    if (indicatorCount === 0) {{
        mainChartRatio = 0.60;  // 无子图指标，主图占 60%
    }} else {{
        // 有子图指标时，主图至少占 40% 或 300px
        mainChartRatio = Math.max(0.40, 300 / totalHeight);
    }}

    const volumeRatio = 0.06;  // Volume 固定占 6%
    const indicatorTotalRatio = 1.0 - mainChartRatio - volumeRatio;
    const indicatorRatio = indicatorCount > 0 ? indicatorTotalRatio / indicatorCount : 0;

    // 从顶部开始计算 domain
    let currentTop = 1.0;
    const domains = {{}};

    // 主图在顶部
    domains.price = [currentTop - mainChartRatio, currentTop];
    currentTop -= mainChartRatio;

    // Volume 在主图下方
    domains.volume = [currentTop - volumeRatio, currentTop];
    currentTop -= volumeRatio;

    // 子图指标依次向下排列
    if (enabledIndicators.includes('OBV')) {{
        domains.obv = [currentTop - indicatorRatio, currentTop];
        currentTop -= indicatorRatio;
    }}

    if (enabledIndicators.includes('ADX')) {{
        domains.adx = [currentTop - indicatorRatio, currentTop];
        currentTop -= indicatorRatio;
    }}

    if (enabledIndicators.includes('ATR')) {{
        domains.atr = [currentTop - indicatorRatio, currentTop];
        currentTop -= indicatorRatio;
    }}

    if (enabledIndicators.includes('RSI')) {{
        domains.rsi = [currentTop - indicatorRatio, currentTop];
        currentTop -= indicatorRatio;
    }}

    if (enabledIndicators.includes('MACD')) {{
        domains.macd = [currentTop - indicatorRatio, currentTop];
        currentTop -= indicatorRatio;
    }}

    return domains;
}}

function renderChart(startIdx, preserveView) {{
    const {{ slice }} = getCurrentData(startIdx);
    currentStartIndex = startIdx;

    const traces = [
        {{
            x: slice.timestamps,
            open: slice.open,
            high: slice.high,
            low: slice.low,
            close: slice.close,
            type: 'candlestick',
            name: 'K-line',
            increasing: {{line: {{color: COLORS.bullish}}}},
            decreasing: {{line: {{color: COLORS.bearish}}}},
            xaxis: 'x',
            yaxis: 'y'
        }},
        {{
            x: slice.timestamps,
            y: slice.price_ma,
            type: 'scatter',
            mode: 'lines',
            name: 'Price MA(20)',
            line: {{color: COLORS.ma_line, width: 1.5, dash: 'dash'}},
            xaxis: 'x',
            yaxis: 'y'
        }}
    ];

    const domains = getYAxisDomains();
    // 子图指标（需要独立 Y 轴）
    const subPlotIndicators = ['OBV', 'ADX', 'ATR', 'RSI', 'MACD'];
    const indicatorCount = enabledIndicators.filter(i => subPlotIndicators.includes(i)).length;
    // 动态高度：基础 500px + 每个子图指标 120px
    const dynamicHeight = 500 + indicatorCount * 120;
    const layout = {{
        title: {{ text: slice.timestamps[0] + ' ~ ' + slice.timestamps[slice.timestamps.length-1] + ' (' + slice.timestamps.length + ' K-lines)', x: 0.5, font: {{size: 14}} }},
        height: dynamicHeight,
        template: 'plotly_white',
        hovermode: 'x unified',
        margin: {{l: {margin_l}, r: {margin_r}, t: {margin_t}, b: {margin_b}}},
        legend: {{orientation: 'h', y: 1.02, x: 1, xanchor: 'right'}},
        dragmode: 'pan'
    }};

    // 动态Y轴配置
    layout.grid = {{rows: 1, columns: 1, pattern: 'independent'}};
    layout.xaxis = {{rangeslider: {{visible: false}}, fixedrange: false, tickformat: '%Y-%m-%d %H:%M', hoverformat: '%Y-%m-%d %H:%M'}};

    // 主图Y轴
    // 主图Y轴 - 需要考虑所有主图叠加指标的范围
    let minPrice = Math.min(...slice.low.filter(v => v)) * 0.998;
    let maxPrice = Math.max(...slice.high.filter(v => v)) * 1.002;

    // 布林带可能超出 K 线范围，需要包含
    if (enabledIndicators.includes('BB') && slice.bb_upper && slice.bb_lower) {{
        const bbMin = Math.min(...slice.bb_lower.filter(v => v)) * 0.998;
        const bbMax = Math.max(...slice.bb_upper.filter(v => v)) * 1.002;
        minPrice = Math.min(minPrice, bbMin);
        maxPrice = Math.max(maxPrice, bbMax);
    }}

    // FVG 区域也可能超出当前 K 线范围
    if (enabledIndicators.includes('FVG')) {{
        (slice.fvg_bullish || []).forEach(fvg => {{
            minPrice = Math.min(minPrice, fvg.low * 0.998);
            maxPrice = Math.max(maxPrice, fvg.high * 1.002);
        }});
        (slice.fvg_bearish || []).forEach(fvg => {{
            minPrice = Math.min(minPrice, fvg.low * 0.998);
            maxPrice = Math.max(maxPrice, fvg.high * 1.002);
        }});
    }}

    layout.yaxis = {{domain: domains.price, title: '', rangeslider: {{visible: false}}, fixedrange: false, nticks: 8, range: [minPrice, maxPrice]}};

    // 用于存储右上角指标名称标注
    const annotations = [];

    // 主图叠加指标名称（右上角显示）
    const mainChartIndicators = [];
    if (enabledIndicators.includes('BB')) mainChartIndicators.push('BB');
    if (enabledIndicators.includes('FVG')) mainChartIndicators.push('FVG');
    if (enabledIndicators.includes('Swing')) mainChartIndicators.push('Swing');
    if (mainChartIndicators.length > 0) {{
        annotations.push({{
            x: 0.98,
            y: 0.98,
            xref: 'paper',
            yref: 'paper',
            xanchor: 'right',
            yanchor: 'top',
            text: mainChartIndicators.join(' | '),
            showarrow: false,
            font: {{ size: 12, color: '#666' }},
            bgcolor: 'rgba(255,255,255,0.8)',
            bordercolor: '#ccc',
            borderwidth: 1,
            borderpad: 4
        }});
    }}

    // 动态分配 Y 轴编号（y2, y3, y4...）
    let yAxisIndex = 2;
    const yAxisMap = {{}};  // 指标名 -> yaxis 编号

    // OBV 指标
    if (enabledIndicators.includes('OBV')) {{
        yAxisMap.OBV = 'y' + yAxisIndex;
        traces.push({{ x: slice.timestamps, y: slice.obv, type: 'scatter', mode: 'lines', name: 'OBV', line: {{color: COLORS.obv_line, width: 1}}, xaxis: 'x', yaxis: yAxisMap.OBV, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: slice.obv_ma, type: 'scatter', mode: 'lines', name: 'OBV MA(20)', line: {{color: COLORS.ma_line, width: 1.5, dash: 'dash'}}, xaxis: 'x', yaxis: yAxisMap.OBV, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: slice.obv.map((v, i) => v > slice.obv_ma[i] ? v : slice.obv_ma[i]), type: 'scatter', mode: 'lines', name: 'OBV Bullish', fill: 'tonexty', fillcolor: COLORS.obv_bullish_fill, line: {{width: 0}}, xaxis: 'x', yaxis: yAxisMap.OBV, showlegend: false, hoverinfo: 'skip' }});
        traces.push({{ x: slice.timestamps, y: slice.obv.map((v, i) => v < slice.obv_ma[i] ? v : slice.obv_ma[i]), type: 'scatter', mode: 'lines', name: 'OBV Bearish', fill: 'tonexty', fillcolor: COLORS.obv_bearish_fill, line: {{width: 0}}, xaxis: 'x', yaxis: yAxisMap.OBV, showlegend: false, hoverinfo: 'skip' }});
        layout['yaxis' + yAxisIndex] = {{domain: domains.obv, title: '', fixedrange: false}};
        // 右上角标注
        annotations.push({{ x: 0.98, y: domains.obv[1] - 0.02, xref: 'paper', yref: 'paper', xanchor: 'right', yanchor: 'top', text: 'OBV', showarrow: false, font: {{ size: 11, color: '#666' }}, bgcolor: 'rgba(255,255,255,0.7)' }});
        yAxisIndex++;
    }}

    // ADX 指标
    if (enabledIndicators.includes('ADX')) {{
        yAxisMap.ADX = 'y' + yAxisIndex;
        traces.push({{ x: slice.timestamps, y: slice.adx, type: 'scatter', mode: 'lines', name: 'ADX', line: {{color: COLORS.adx_line, width: 1.5}}, xaxis: 'x', yaxis: yAxisMap.ADX, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: Array(slice.timestamps.length).fill(25), type: 'scatter', mode: 'lines', name: 'Threshold (25)', line: {{color: COLORS.adx_threshold, width: 1.5, dash: 'dash'}}, xaxis: 'x', yaxis: yAxisMap.ADX, hoverinfo: 'skip', showlegend: false }});
        layout['yaxis' + yAxisIndex] = {{domain: domains.adx, title: '', range: [0, Math.max(...slice.adx.map(v => v || 0)) * 1.1], fixedrange: false}};
        annotations.push({{ x: 0.98, y: domains.adx[1] - 0.02, xref: 'paper', yref: 'paper', xanchor: 'right', yanchor: 'top', text: 'ADX', showarrow: false, font: {{ size: 11, color: '#666' }}, bgcolor: 'rgba(255,255,255,0.7)' }});
        yAxisIndex++;
    }}

    // ATR 指标
    if (enabledIndicators.includes('ATR')) {{
        yAxisMap.ATR = 'y' + yAxisIndex;
        traces.push({{ x: slice.timestamps, y: slice.atr, type: 'scatter', mode: 'lines', name: 'ATR(14)', line: {{color: COLORS.atr_line, width: 1.5}}, xaxis: 'x', yaxis: yAxisMap.ATR, showlegend: false }});
        layout['yaxis' + yAxisIndex] = {{domain: domains.atr, title: '', fixedrange: false}};
        annotations.push({{ x: 0.98, y: domains.atr[1] - 0.02, xref: 'paper', yref: 'paper', xanchor: 'right', yanchor: 'top', text: 'ATR(14)', showarrow: false, font: {{ size: 11, color: '#666' }}, bgcolor: 'rgba(255,255,255,0.7)' }});
        yAxisIndex++;
    }}

    // RSI 指标
    if (enabledIndicators.includes('RSI')) {{
        yAxisMap.RSI = 'y' + yAxisIndex;
        traces.push({{ x: slice.timestamps, y: slice.rsi, type: 'scatter', mode: 'lines', name: 'RSI', line: {{color: COLORS.rsi_line, width: 1.5}}, xaxis: 'x', yaxis: yAxisMap.RSI, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: Array(slice.timestamps.length).fill(70), type: 'scatter', mode: 'lines', name: 'Overbought', line: {{color: 'red', width: 1, dash: 'dash'}}, xaxis: 'x', yaxis: yAxisMap.RSI, hoverinfo: 'skip', showlegend: false }});
        traces.push({{ x: slice.timestamps, y: Array(slice.timestamps.length).fill(30), type: 'scatter', mode: 'lines', name: 'Oversold', line: {{color: 'green', width: 1, dash: 'dash'}}, xaxis: 'x', yaxis: yAxisMap.RSI, hoverinfo: 'skip', showlegend: false }});
        layout['yaxis' + yAxisIndex] = {{domain: domains.rsi, title: '', range: [0, 100], fixedrange: false}};
        annotations.push({{ x: 0.98, y: domains.rsi[1] - 0.02, xref: 'paper', yref: 'paper', xanchor: 'right', yanchor: 'top', text: 'RSI(14)', showarrow: false, font: {{ size: 11, color: '#666' }}, bgcolor: 'rgba(255,255,255,0.7)' }});
        yAxisIndex++;
    }}

    // MACD 指标
    if (enabledIndicators.includes('MACD')) {{
        yAxisMap.MACD = 'y' + yAxisIndex;
        traces.push({{ x: slice.timestamps, y: slice.macd, type: 'scatter', mode: 'lines', name: 'MACD', line: {{color: COLORS.macd_line, width: 1.5}}, xaxis: 'x', yaxis: yAxisMap.MACD, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: slice.macd_signal, type: 'scatter', mode: 'lines', name: 'Signal', line: {{color: COLORS.macd_signal, width: 1.5}}, xaxis: 'x', yaxis: yAxisMap.MACD, showlegend: false }});
        traces.push({{ x: slice.timestamps, y: slice.macd_hist, type: 'bar', name: 'Histogram', marker: {{color: slice.macd_hist.map(v => v >= 0 ? COLORS.macd_hist_pos : COLORS.macd_hist_neg)}}, xaxis: 'x', yaxis: yAxisMap.MACD, showlegend: false }});
        layout['yaxis' + yAxisIndex] = {{domain: domains.macd, title: '', fixedrange: false}};
        annotations.push({{ x: 0.98, y: domains.macd[1] - 0.02, xref: 'paper', yref: 'paper', xanchor: 'right', yanchor: 'top', text: 'MACD(12,26,9)', showarrow: false, font: {{ size: 11, color: '#666' }}, bgcolor: 'rgba(255,255,255,0.7)' }});
        yAxisIndex++;
    }}

    // 应用标注到 layout
    if (annotations.length > 0) {{
        layout.annotations = annotations;
    }}

    // 布林带
    if (enabledIndicators.includes('BB')) {{
        traces.push({{ x: slice.timestamps, y: slice.bb_upper, type: 'scatter', mode: 'lines', name: 'BB Upper', line: {{color: COLORS.bb_line, width: 1, dash: 'dot'}}, xaxis: 'x', yaxis: 'y' }});
        traces.push({{ x: slice.timestamps, y: slice.bb_middle, type: 'scatter', mode: 'lines', name: 'BB Middle', line: {{color: COLORS.bb_line, width: 1}}, xaxis: 'x', yaxis: 'y' }});
        traces.push({{ x: slice.timestamps, y: slice.bb_lower, type: 'scatter', mode: 'lines', name: 'BB Lower', line: {{color: COLORS.bb_line, width: 1, dash: 'dot'}}, fill: 'tonexty', fillcolor: 'rgba(0, 0, 255, 0.1)', xaxis: 'x', yaxis: 'y' }});
    }}

    // FVG 区域
    if (enabledIndicators.includes('FVG')) {{
        const fvgShapes = [];
        (slice.fvg_bullish || []).forEach(fvg => {{
            fvgShapes.push({{ type: 'rect', x0: fvg.start_time, x1: fvg.end_time, y0: fvg.low, y1: fvg.high, fillcolor: COLORS.fvg_bullish_fill, line: {{width: 0}}, xref: 'x', yref: 'y' }});
        }});
        (slice.fvg_bearish || []).forEach(fvg => {{
            fvgShapes.push({{ type: 'rect', x0: fvg.start_time, x1: fvg.end_time, y0: fvg.low, y1: fvg.high, fillcolor: COLORS.fvg_bearish_fill, line: {{width: 0}}, xref: 'x', yref: 'y' }});
        }});
        layout.shapes = fvgShapes;
    }}

    // Swing Points
    if (enabledIndicators.includes('Swing')) {{
        (slice.swing_highs || []).forEach(swing => {{
            traces.push({{ x: [swing.time], y: [swing.price], type: 'scatter', mode: 'markers', name: 'Swing High',
                text: 'HH ' + swing.price.toFixed(4), hoverinfo: 'text',
                marker: {{symbol: 'circle', size: 8, color: 'rgba(0, 128, 0, 0.7)', line: {{width: 2, color: 'darkgreen'}}}},
                xaxis: 'x', yaxis: 'y', showlegend: false }});
        }});
        (slice.swing_lows || []).forEach(swing => {{
            traces.push({{ x: [swing.time], y: [swing.price], type: 'scatter', mode: 'markers', name: 'Swing Low',
                text: 'LL ' + swing.price.toFixed(4), hoverinfo: 'text',
                marker: {{symbol: 'circle', size: 8, color: 'rgba(255, 0, 0, 0.7)', line: {{width: 2, color: 'darkred'}}}},
                xaxis: 'x', yaxis: 'y', showlegend: false }});
        }});
    }}

    // 交易标记
    slice.trades.forEach(t => {{
        const entryColor = t.type === 'LONG' ? COLORS.long_entry : COLORS.short_entry;
        const entrySymbol = t.type === 'LONG' ? 'triangle-up' : 'triangle-down';
        const entryHover = '<b>' + t.type + ' OPEN</b> (' + t.entry_time + ', ' + t.entry_price + ')';
        traces.push({{
            x: [t.entry_time],
            y: [t.entry_price],
            type: 'scatter',
            mode: 'markers',
            name: t.type + ' OPEN',
            text: entryHover,
            hoverinfo: 'text',
            marker: {{symbol: entrySymbol, size: 12, color: entryColor, line: {{width: 2, color: 'black'}}}},
            xaxis: 'x',
            yaxis: 'y',
            showlegend: false
        }});
        const exitColor = t.pnl > 0 ? COLORS.profit_exit : COLORS.loss_exit;
        const pnlSign = t.pnl > 0 ? '+' : '';
        const exitHover = '<b>' + t.type + ' CLOSE</b> (' + t.exit_time + ', ' + t.exit_price + ', ' + pnlSign + t.pnl.toFixed(2) + ')';
        traces.push({{
            x: [t.exit_time],
            y: [t.exit_price],
            type: 'scatter',
            mode: 'markers',
            name: t.type + ' CLOSE',
            text: exitHover,
            hoverinfo: 'text',
            marker: {{symbol: 'x', size: 12, color: exitColor, line: {{width: 2}}}},
            xaxis: 'x',
            yaxis: 'y',
            showlegend: false
        }});
    }});

    const config = {{ responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] }};
    const promise = preserveView ? Plotly.react('chartContainer', traces, layout, config) : Plotly.newPlot('chartContainer', traces, layout, config);
    promise.then(() => {{
        const chartContainer = document.getElementById('chartContainer');
        chartContainer.on('plotly_relayout', function(eventdata) {{
            if (isRelayouting) return;
            if (eventdata['xaxis.range[0]'] && eventdata['xaxis.range[1]']) {{
                const startTime = new Date(eventdata['xaxis.range[0]']);
                const startTimestamp = startTime.toISOString().slice(0, 16).replace('T', ' ');
                let newStartIdx = allData.timestamps.findIndex(t => t >= startTimestamp);
                if (newStartIdx === -1) newStartIdx = TOTAL_KLINES - DISPLAY_COUNT;
                if (newStartIdx < 0) newStartIdx = 0;
                if (Math.abs(newStartIdx - currentStartIndex) > DISPLAY_COUNT * 0.3) {{
                    isRelayouting = true;
                    renderChart(newStartIdx, true);
                    setTimeout(() => {{ isRelayouting = false; }}, 100);
                }}
            }}
        }});
    }});
    renderTable(slice);
}}

function renderTable(slice) {{
    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = '';
    const klineMap = {{}};
    for (let i = 0; i < slice.timestamps.length; i++) {{
        klineMap[slice.timestamps[i]] = {{ open: slice.open[i], high: slice.high[i], low: slice.low[i], close: slice.close[i], price_ma: slice.price_ma[i], volume: slice.volume[i] }};
        if (slice.obv) klineMap[slice.timestamps[i]].obv = slice.obv[i];
        if (slice.obv_ma) klineMap[slice.timestamps[i]].obv_ma = slice.obv_ma[i];
        if (slice.adx) klineMap[slice.timestamps[i]].adx = slice.adx[i];
    }}
    const tradeMap = {{}};
    slice.trades.forEach(t => {{ tradeMap[t.entry_time] = {{type: 'entry', data: t}}; tradeMap[t.exit_time] = {{type: 'exit', data: t}}; }});
    const allTimes = [...slice.timestamps];
    slice.trades.forEach(t => {{ if (!allTimes.includes(t.entry_time)) allTimes.push(t.entry_time); if (!allTimes.includes(t.exit_time)) allTimes.push(t.exit_time); }});
    allTimes.sort();
    allTimes.forEach(ts => {{
        const tr = document.createElement('tr');
        const kline = klineMap[ts];
        const trade = tradeMap[ts];
        if (kline) {{
            let obvCell = '<td>-</td><td>-</td><td>-</td>';
            if (slice.obv && slice.obv_ma) {{
                const obvSig = kline.obv > kline.obv_ma ? 'Bullish' : 'Bearish';
                obvCell = '<td>' + kline.obv + '</td><td>' + kline.obv_ma + '</td><td class="' + (obvSig === 'Bullish' ? 'positive' : 'negative') + '">' + obvSig + '</td>';
            }}
            let adxCell = '<td>-</td><td>-</td>';
            if (slice.adx) {{
                const adxSig = kline.adx >= 25 ? 'Trend' : 'No Trend';
                adxCell = '<td>' + kline.adx + '</td><td class="' + (adxSig === 'Trend' ? 'positive' : '') + '">' + adxSig + '</td>';
            }}
            tr.innerHTML = '<td>' + ts + '</td><td>' + kline.open + '</td><td>' + kline.high + '</td><td>' + kline.low + '</td><td><strong>' + kline.close + '</strong></td><td>' + kline.price_ma + '</td>' + obvCell + adxCell + '<td>' + kline.volume + '</td><td class="entry-col"></td><td class="exit-col"></td>';
            tbody.appendChild(tr);
        }} else if (trade) {{
            const t = trade.data;
            if (trade.type === 'entry') {{
                tr.className = t.type === 'LONG' ? 'entry-long' : 'entry-short';
                tr.innerHTML = '<td><strong>' + ts + '</strong></td><td>-</td><td>-</td><td>-</td><td><strong>' + t.entry_price + '</strong></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td class="entry-col"><strong>' + t.type + ' OPEN @ ' + t.entry_price + '</strong></td><td class="exit-col"></td>';
            }} else {{
                const pnlStr = t.pnl >= 0 ? '+' + t.pnl : t.pnl;
                tr.className = t.pnl > 0 ? 'exit-profit' : 'exit-loss';
                tr.innerHTML = '<td><strong>' + ts + '</strong></td><td>-</td><td>-</td><td>-</td><td><strong>' + t.exit_price + '</strong></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td class="entry-col"></td><td class="exit-col"><strong>' + t.type + ' CLOSE @ ' + t.exit_price + ' (PnL: ' + pnlStr + ')</strong></td>';
            }}
            tbody.appendChild(tr);
        }}
    }});
}}

document.getElementById('filterInput').addEventListener('input', function() {{
    const filter = this.value.toLowerCase();
    document.querySelectorAll('#tableBody tr').forEach(tr => {{ tr.style.display = tr.textContent.toLowerCase().includes(filter) ? '' : 'none'; }});
}});

window.addEventListener('resize', function() {{
    const autoCheckbox = document.getElementById('autoAdapt');
    if (!autoCheckbox.checked) return;
    const newCount = getAutoDisplayCount();
    if (newCount !== DISPLAY_COUNT) {{
        DISPLAY_COUNT = newCount;
        document.getElementById('displayCountInput').value = DISPLAY_COUNT;
        renderChart(Math.min(currentStartIndex, Math.max(0, TOTAL_KLINES - DISPLAY_COUNT)), true);
        updateAdaptHint();
    }}
}});

// 初始化
initIndicatorCheckboxes();
updateAdaptHint();
currentStartIndex = Math.max(0, TOTAL_KLINES - DISPLAY_COUNT);
renderChart(currentStartIndex, false);
</script>
</body>
</html>'''