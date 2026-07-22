// AI-generated insights panel (verdict card, catalysts/risks, source
// breakdown, copy-to-clipboard report) shown on the stock analysis view.
//
// Split out of index-page.js. Its only external state is window._lastInsights
// / window._lastKeywords, which were already global (set by index-page.js's
// displayResults before calling into this module), so no extra namespace
// plumbing was needed for state — just the one exported entry point below.
document.addEventListener('DOMContentLoaded', function() {
    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));

    // Display insights function
    function displayInsights(insights) {
        const insightsContent = document.getElementById('insightsContent');
        if (!insightsContent || !insights) return;

        if (insights.verdict) {
            displayRichInsights(insightsContent, insights);
        } else {
            displayLegacyInsights(insightsContent, insights);
        }
    }

    function displayLegacyInsights(el, insights) {
        const marketOutlook = escapeHtml(insights.market_outlook || '');
        const opportunities = (insights.opportunities || []).map(opp => `<li class="mb-2">${escapeHtml(opp)}</li>`).join('');
        const keyPoints = (insights.key_points || []).map(point => `<li class="mb-2">${escapeHtml(point)}</li>`).join('');
        const riskFactors = (insights.risk_factors || []).map(risk => `<li class="mb-2">${escapeHtml(risk)}</li>`).join('');

        el.innerHTML = `
            <div class="row">
                <div class="col-md-6 mb-4">
                    <h6 class="text-primary mb-3">Market Outlook</h6>
                    <p class="mb-3">${marketOutlook}</p>
                    <h6 class="text-success mb-3">Opportunities</h6>
                     <ul class="list-unstyled">
                        ${opportunities}
                    </ul>
                </div>
                <div class="col-md-6 mb-4">
                    <h6 class="text-warning mb-3">Key Points</h6>
                    <ul class="list-unstyled">
                        ${keyPoints}
                    </ul>
                    <h6 class="text-danger mb-3">Risk Factors</h6>
                    <ul class="list-unstyled">
                        ${riskFactors}
                    </ul>
                </div>
            </div>`;
    }

    function displayRichInsights(el, ins) {
        const v = ins.verdict || {};
        const signalColor = v.signal === 'Bullish' ? 'var(--positive)' : v.signal === 'Bearish' ? 'var(--negative)' : 'var(--neutral-warn)';
        const signalBadge = v.signal === 'Bullish' ? 'bg-success' : v.signal === 'Bearish' ? 'bg-danger' : 'bg-warning text-dark';
        const confBadge = v.confidence_label === 'High' ? 'bg-success' : v.confidence_label === 'Medium' ? 'bg-warning text-dark' : 'bg-danger';

        function sevBadge(s) {
            const cls = s === 'High' ? 'bg-danger' : s === 'Medium' ? 'bg-warning text-dark' : 'bg-secondary';
            return `<span class="badge ${cls} severity-badge">${escapeHtml(s)}</span>`;
        }

        // Build catalysts
        const catalystsHtml = (ins.catalysts || []).map(c => `
            <div class="catalyst-item mb-2">
                <span class="badge bg-secondary me-2">${escapeHtml(c.tag || '')}</span>
                <span>${escapeHtml(c.text || '')}</span>
            </div>
        `).join('') || '<p class="text-muted mb-0">No catalysts identified.</p>';

        // Build risks
        const risksHtml = (ins.risks || []).map(r => `
            <div class="risk-item mb-2">

                ${sevBadge(r.severity || 'Low')}
                <span class="ms-2">${escapeHtml(r.text || '')}</span>
            </div>
        `).join('') || '<p class="text-muted mb-0">No specific risks identified.</p>';

        // Source breakdown bar
        const sb = ins.source_breakdown || {};
        const bullPct = Math.max(0, Math.min(100, Number(sb.bullish_pct) || 0));
        const neuPct = Math.max(0, Math.min(100, Number(sb.neutral_pct) || 0));
        const bearPct = Math.max(0, Math.min(100, Number(sb.bearish_pct) || 0));

        // Velocity
        const vel = ins.sentiment_velocity || {};
        const trend = ins.trending || {};
        const keywords = (ins.keywords_enriched || window._lastKeywords || []).slice(0, 12);
        const keywordHtml = keywords.map(kw => {
            return `<span class="badge bg-secondary me-1 mb-1 insights-keyword-badge">${escapeHtml(kw.text || kw.word || '')}</span>`;
        }).join('') || '<span class="text-muted">No keyword cluster available.</span>';

        el.innerHTML = `
            <!-- Verdict -->
            <div class="verdict-card p-3 mb-3">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <div class="d-flex align-items-center insights-badge-row">
                        <span class="badge ${signalBadge} verdict-badge me-3">${escapeHtml(v.signal || 'Neutral')}</span>
                        <span class="badge ${confBadge} verdict-badge">${escapeHtml(v.confidence_label || 'Low')} confidence</span>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary copy-report-btn" title="Copy report to clipboard">
                        Copy
                    </button>
                </div>
                <p class="mb-1 fw-bold insights-one-liner">${escapeHtml(v.one_liner || '')}</p>
                ${v.confidence_explanation ? `<p class="text-muted mb-2 insights-conf-explanation">${escapeHtml(v.confidence_explanation)}</p>` : ''}
                ${ins.analyst_note ? `<p class="mb-0 insights-analyst-note">${escapeHtml(ins.analyst_note)}</p>` : ''}
            </div>

            <!-- Velocity + Topics -->
            <div class="row mb-3">
                <div class="col-md-4 mb-3 mb-md-0">
                    <h6 class="mb-2">SENTIMENT VELOCITY</h6>
                    <div class="insights-meta-block">
                        <span class="insights-velocity-trend">${escapeHtml(vel.trend || 'stable')}</span>
                        ${vel.label ? ` - ${escapeHtml(vel.label)}` : ''}
                    </div>
                </div>
                <div class="col-md-4 mb-3 mb-md-0">
                    <h6 class="mb-2">TRENDING WATCH</h6>
                    <div class="insights-meta-block">
                        <span class="insights-trend-category">${escapeHtml(trend.category || 'other')}</span>
                        ${trend.what_to_watch ? ` - ${escapeHtml(trend.what_to_watch)}` : ''}
                    </div>
                </div>
                <div class="col-md-4">
                    <h6 class="mb-2">KEYWORDS</h6>
                    <div>${keywordHtml}</div>
                </div>
            </div>

            <!-- Catalysts + Risks -->
            <div class="row mb-3">
                <div class="col-md-6 mb-3 mb-md-0">
                    <h6 class="text-success mb-3">POSITIVES</h6>
                    ${catalystsHtml}
                </div>
                <div class="col-md-6">
                    <h6 class="text-danger mb-3">RISKS</h6>
                    ${risksHtml}
                </div>
            </div>

            <!-- Source Breakdown -->
            <div class="row mb-3">
                <div class="col-md-12">
                    <h6 class="mb-2">SOURCE BREAKDOWN</h6>
                    <div class="source-bar mb-2">
                        ${bullPct > 0 ? `<div class="source-bar-bull" title="Bullish ${bullPct}%"></div>` : ''}
                        ${neuPct > 0 ? `<div class="source-bar-neu" title="Neutral ${neuPct}%"></div>` : ''}
                        ${bearPct > 0 ? `<div class="source-bar-bear" title="Bearish ${bearPct}%"></div>` : ''}
                    </div>
                    <div class="d-flex justify-content-between insights-source-pct-row">
                        <span class="text-success">${bullPct}% Bullish</span>
                        <span class="text-muted">${neuPct}% Neutral</span>
                        <span class="text-danger">${bearPct}% Bearish</span>
                    </div>
                    ${sb.analyst_takeaway ? `<p class="text-muted mt-1 mb-0 insights-analyst-takeaway">${escapeHtml(sb.analyst_takeaway)}</p>` : ''}
                </div>
            </div>
        `;

        // Dynamic styling that CSP's style-src (without 'unsafe-inline') can't
        // express as HTML attributes: applied via CSSOM after the markup above
        // has been inserted, which is not blocked.
        const verdictCardEl = el.querySelector('.verdict-card');
        if (verdictCardEl) {
            verdictCardEl.style.borderLeft = `4px solid ${signalColor}`;
        }

        const keywordBadgeEls = el.querySelectorAll('.insights-keyword-badge');
        keywordBadgeEls.forEach((node, index) => {
            const kw = keywords[index];
            if (!kw) return;
            const sentimentName = String(kw.sentiment || 'neutral').toLowerCase();
            node.style.color = sentimentName === 'positive'
                ? 'var(--positive)'
                : sentimentName === 'negative'
                    ? 'var(--negative)'
                    : 'var(--text-muted)';
        });

        const sourceBarBullEl = el.querySelector('.source-bar-bull');
        if (sourceBarBullEl) sourceBarBullEl.style.width = bullPct + '%';
        const sourceBarNeuEl = el.querySelector('.source-bar-neu');
        if (sourceBarNeuEl) sourceBarNeuEl.style.width = neuPct + '%';
        const sourceBarBearEl = el.querySelector('.source-bar-bear');
        if (sourceBarBearEl) sourceBarBearEl.style.width = bearPct + '%';

        const copyBtn = el.querySelector('.copy-report-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', function() {
                copyReport(this);
            });
        }
    }

    function copyReport(btn) {
        const ins = window._lastInsights;
        if (!ins) return;
        const v = ins.verdict || {};
        const report = ins.report_summary || {};
        const catalysts = (ins.catalysts || []).map(c => `  - [${c.direction}] ${c.tag}: ${c.text}`).join('\n');
        const risks = (ins.risks || []).map(r => `  - [${r.severity}] ${r.text}`).join('\n');
        const text = [
            report.title || '',
            '',
            `Signal: ${v.signal} (${v.confidence_label} confidence)`,
            v.one_liner || '',
            '',
            report.executive_summary || '',
            '',
            catalysts ? `Catalysts:\n${catalysts}` : '',
            risks ? `Risks:\n${risks}` : '',
            '',
            report.disclaimer || '',
        ].filter(Boolean).join('\n');

        navigator.clipboard.writeText(text).then(() => {
            const orig = btn.innerHTML;
            btn.innerHTML = 'Copied';
            setTimeout(() => { btn.innerHTML = orig; }, 2000);
        });
    }

    window.StockScreenInsights = window.StockScreenInsights || {};
    window.StockScreenInsights.displayInsights = displayInsights;
});
