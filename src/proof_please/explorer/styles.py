"""Visual style primitives for the Streamlit explorer."""

APP_STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
    --pp-bg: #f6f3eb;
    --pp-bg-soft: #fcfaf5;
    --pp-ink: #172228;
    --pp-ink-muted: #41535d;
    --pp-ink-soft: #61717b;
    --pp-accent: #1f6f58;
    --pp-border: #d8ccb8;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    color: var(--pp-ink);
}

h1, h2, h3 {
    font-family: 'Fraunces', serif;
    letter-spacing: -0.02em;
    color: var(--pp-ink);
}

[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(1200px 540px at 12% -8%, #e6f1ea 0%, rgba(230, 241, 234, 0) 62%),
        radial-gradient(960px 360px at 98% 0%, #f8ebd2 0%, rgba(248, 235, 210, 0) 70%),
        var(--pp-bg);
    color: var(--pp-ink);
}

[data-testid="stAppViewBlockContainer"] {
    color: var(--pp-ink);
}

[data-testid="stAppViewBlockContainer"] p,
[data-testid="stAppViewBlockContainer"] li,
[data-testid="stAppViewBlockContainer"] label,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] * {
    color: var(--pp-ink-muted) !important;
}

[data-testid="stSidebar"] {
    background: #1f222f;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] * {
    color: #dbe3ea !important;
}

[data-testid="stSidebar"] [data-baseweb="input"] > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #0f1724;
    border: 1px solid #3f4d63;
}

[data-testid="stSidebar"] [data-baseweb="input"] input,
[data-testid="stSidebar"] [data-baseweb="select"] * {
    color: #eef4f9 !important;
}

.hero {
    background: linear-gradient(120deg, rgba(255, 255, 255, 0.86), rgba(248, 243, 231, 0.86));
    border: 1px solid var(--pp-border);
    border-radius: 18px;
    padding: 1.1rem 1.2rem;
    box-shadow: 0 18px 32px rgba(56, 56, 44, 0.1);
    margin-bottom: 0.8rem;
    animation: riseIn 0.38s ease-out both;
}

.hero h1 {
    color: var(--pp-ink) !important;
}

.hero-kicker {
    color: #2f5c50;
    font-size: 0.82rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin: 0;
}

.hero-subtext {
    color: var(--pp-ink-muted);
    margin: 0.4rem 0 0;
    line-height: 1.45;
}

.card-shell {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid #e3d7c4;
    border-radius: 14px;
    padding: 0.9rem 1rem;
    box-shadow: 0 8px 20px rgba(50, 44, 35, 0.07);
    animation: riseIn 0.28s ease-out both;
}

.claim-line {
    margin: 0;
    line-height: 1.45;
    color: var(--pp-ink);
    font-size: 1.03rem;
}

.meta-note {
    font-family: 'IBM Plex Mono', monospace;
    color: var(--pp-ink-soft);
    font-size: 0.82rem;
}

[data-testid="stWidgetLabel"] p,
[data-testid="stCheckbox"] p,
[data-testid="stMarkdownContainer"] h4 {
    color: var(--pp-ink-muted) !important;
    font-weight: 600;
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div {
    background: var(--pp-bg-soft);
    border: 1px solid var(--pp-border);
}

[data-baseweb="input"] input,
[data-baseweb="select"] * {
    color: var(--pp-ink) !important;
}

[data-testid="stTabs"] [role="tab"] {
    color: var(--pp-ink-soft) !important;
    font-weight: 600;
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: var(--pp-accent) !important;
}

[data-testid="stMetric"] {
    background: rgba(255, 252, 246, 0.85);
    border: 1px solid var(--pp-border);
    border-radius: 12px;
    padding: 0.75rem 0.75rem 0.7rem;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricValue"] {
    color: var(--pp-ink) !important;
}

.segment-row {
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid #e7dbc8;
    border-radius: 12px;
    padding: 0.7rem 0.85rem;
    margin-bottom: 0.45rem;
    transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.segment-row--claimed {
    border-left: 4px solid rgba(31, 111, 88, 0.62);
}

.segment-row--active {
    border-color: rgba(31, 111, 88, 0.92);
    box-shadow: 0 8px 18px rgba(26, 49, 43, 0.1);
    transform: translateY(-1px);
}

.segment-row--match {
    background: linear-gradient(
        120deg,
        rgba(248, 243, 231, 0.92),
        rgba(228, 241, 236, 0.9)
    );
}

.segment-row-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.42rem;
    margin-bottom: 0.3rem;
    font-size: 0.78rem;
    color: var(--pp-ink-soft);
    font-family: 'IBM Plex Mono', monospace;
}

.segment-seg-id {
    font-weight: 600;
    color: var(--pp-ink-muted);
}

.segment-badge {
    margin-left: auto;
    background: rgba(31, 111, 88, 0.15);
    color: #205a48;
    border: 1px solid rgba(31, 111, 88, 0.3);
    border-radius: 999px;
    padding: 0.1rem 0.46rem;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
}

.segment-row-text {
    margin: 0;
    color: var(--pp-ink);
    line-height: 1.45;
}

@keyframes riseIn {
    from {
        opacity: 0;
        transform: translateY(8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@media (max-width: 768px) {
    .hero {
        padding: 0.9rem;
    }
    .claim-line {
        font-size: 0.96rem;
    }
}

@media (prefers-reduced-motion: reduce) {
    .hero,
    .card-shell,
    .segment-row {
        animation: none !important;
        transition: none !important;
    }
}
</style>
"""
