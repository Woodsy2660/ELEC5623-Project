"""Local Streamlit homepage for evidence-grounded requirement review (FR01–FR03).

Run with ``streamlit run src/review_ui/app.py``. This is a deliberately read-only
preview shell until the persistence and pipeline integrations are available.
"""

import streamlit as st


def _apply_theme() -> None:
    """Apply a self-contained, local dark operations-console theme."""
    st.markdown(
        """
        <style>
          :root { --ink:#eaf1ff; --muted:#91a2c5; --cyan:#56e4ff; --violet:#a78bfa;
                  --green:#5df0ab; --amber:#ffca6b; --line:rgba(128,161,234,.20);
                  --panel:rgba(12,24,50,.82); }
          .stApp { color:var(--ink); background-color:#050914;
            background-image:linear-gradient(rgba(81,115,178,.06) 1px,transparent 1px),
              linear-gradient(90deg,rgba(81,115,178,.06) 1px,transparent 1px),
              radial-gradient(circle at 74% 3%,rgba(64,83,214,.30),transparent 29%),
              radial-gradient(circle at 15% 58%,rgba(9,156,190,.16),transparent 35%);
            background-size:34px 34px,34px 34px,auto,auto; }
          .block-container { max-width:1500px; padding-top:1.55rem; padding-bottom:3rem; }
          [data-testid="stSidebar"] { background:linear-gradient(180deg,#071426 0%,#091024 100%);
            border-right:1px solid rgba(95,162,240,.18); }
          [data-testid="stSidebar"] * { color:var(--ink); }
          [data-testid="stMetric"] { background:rgba(10,25,53,.74); border:1px solid var(--line);
            border-radius:12px; padding:.85rem 1rem; box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 12px 30px rgba(0,0,0,.16); }
          [data-testid="stMetricLabel"] { color:var(--muted); }
          [data-testid="stMetricValue"] { color:var(--cyan); }
          [data-testid="stTabs"] button { color:var(--muted); font-weight:650; }
          [data-testid="stTabs"] button[aria-selected="true"] { color:var(--cyan); }
          .brand-mark { display:inline-flex; align-items:center; gap:.6rem; color:var(--cyan);
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.74rem; font-weight:800; letter-spacing:.14em; }
          .brand-orb { width:14px; height:14px; border:2px solid var(--cyan); border-radius:50%; box-shadow:0 0 18px var(--cyan); position:relative; }
          .brand-orb:after { content:""; position:absolute; width:4px; height:4px; background:var(--cyan); border-radius:50%; top:3px; left:3px; }
          .eyebrow { color:var(--cyan); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.72rem; font-weight:750; letter-spacing:.13em; text-transform:uppercase; }
          .hero { position:relative; overflow:hidden; border:1px solid rgba(101,188,255,.28);
            background:linear-gradient(110deg,rgba(10,32,72,.97),rgba(27,28,77,.83)); border-radius:17px; padding:2rem 2.1rem; margin:.55rem 0 1.25rem;
            box-shadow:0 22px 55px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.08); }
          .hero:after { content:""; position:absolute; width:330px; height:330px; border:1px solid rgba(86,228,255,.22); border-radius:50%; right:-85px; top:-195px; box-shadow:0 0 50px rgba(86,228,255,.15); }
          .hero h1 { color:#f6f9ff; margin:0; font-size:clamp(2rem,4vw,3.55rem); letter-spacing:-.045em; }
          .hero p { color:#b8c7e7; font-size:1.04rem; margin:.7rem 0 0; max-width:680px; }
          .hero-signal { color:var(--green); margin-top:1.3rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.74rem; letter-spacing:.06em; }
          .panel { background:var(--panel); border:1px solid var(--line); border-radius:13px; padding:1.05rem 1.1rem; min-height:188px;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 16px 38px rgba(0,0,0,.13); }
          .panel-title { color:var(--ink); font-size:.92rem; font-weight:750; margin-bottom:.82rem; }
          .panel-subtitle { color:var(--muted); font-size:.76rem; margin-top:-.55rem; margin-bottom:.8rem; }
          .status { display:inline-block; border-radius:99px; padding:.25rem .62rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.68rem; font-weight:800; letter-spacing:.03em; }
          .pending { background:rgba(255,202,107,.15); color:var(--amber); border:1px solid rgba(255,202,107,.27); }
          .allowed { background:rgba(93,240,171,.13); color:var(--green); border:1px solid rgba(93,240,171,.28); }
          .archived { background:rgba(167,139,250,.14); color:#c4b5fd; border:1px solid rgba(167,139,250,.25); }
          .proposal { color:#eef4ff; font-size:1.08rem; font-weight:720; line-height:1.35; margin:.8rem 0; }
          .detail { color:var(--muted); font-size:.79rem; line-height:1.55; }
          .evidence { color:#dce9ff; border-left:3px solid var(--cyan); background:rgba(78,122,214,.11); padding:.82rem .9rem; border-radius:0 8px 8px 0; line-height:1.55; }
          .trace-row { display:flex; align-items:center; gap:.6rem; padding:.62rem 0; border-bottom:1px solid rgba(131,158,208,.13); color:var(--muted); font-size:.8rem; }
          .trace-row:last-child { border-bottom:0; }
          .trace-dot { width:7px; height:7px; border-radius:50%; background:var(--cyan); box-shadow:0 0 9px var(--cyan); }
          .trace-dot.green { background:var(--green); box-shadow:0 0 9px var(--green); }
          .trace-dot.violet { background:var(--violet); box-shadow:0 0 9px var(--violet); }
          .wireframe { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#8cb5ef; font-size:.72rem; border:1px dashed rgba(104,157,244,.32); border-radius:8px; padding:.7rem; background:rgba(5,11,27,.45); }
          [data-testid="stButton"] button:disabled { opacity:.5; border-color:rgba(137,164,219,.42); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _status(label: str, css_class: str) -> str:
    return f'<span class="status {css_class}">{label}</span>'


def _panel(title: str, subtitle: str, content: str) -> None:
    st.markdown(
        f'<section class="panel"><div class="panel-title">{title}</div>'
        f'<div class="panel-subtitle">{subtitle}</div>{content}</section>',
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand-mark"><span class="brand-orb"></span> CIA // OPS</div>',
            unsafe_allow_html=True,
        )
        st.caption("Evidence-grounded lifecycle review")
        st.divider()
        st.selectbox("Active workspace", ["NORTHSTAR / CLIENT PORTAL"], disabled=True)
        st.caption("LOCAL PREVIEW · SAMPLE DATA")
        st.divider()
        st.markdown('<p class="eyebrow">Review protocol</p>', unsafe_allow_html=True)
        st.markdown("`01` Inspect source evidence")
        st.markdown("`02` Validate lifecycle path")
        st.markdown("`03` Authorise scoped change")
        st.divider()
        st.caption("Human confirmation is required before any register mutation.")


def _render_review_queue() -> None:
    queue, evidence, verdict = st.columns((1.1, 1.5, 1.1), gap="large")
    with queue:
        _panel(
            "01 / PROPOSAL QUEUE",
            "1 of 3 proposals selected",
            f"""{_status("PENDING HUMAN REVIEW", "pending")}
            <div class="proposal">Use SSO instead of email login</div>
            <div class="detail">MODEL RELATION · <b>SUPERSESSION</b><br>
            MATCHED FAMILY · R-014<br>CONFIDENCE IS NOT APPROVAL</div>""",
        )
    with evidence:
        _panel(
            "02 / SOURCE EVIDENCE",
            "Meeting 02 · Turn 018 · Client sponsor",
            """<div class="evidence">“For the staff portal, we will use SSO instead of email and password login.”</div>
            <div class="detail" style="margin-top:.9rem;">✓ SUBSTRING SPAN RESOLVED &nbsp; · &nbsp; ✓ SPEAKER AUTHORITY LOADED</div>""",
        )
    with verdict:
        _panel(
            "03 / SAFETY GATE",
            "Deterministic engine result",
            f"""{_status("ALLOWED AFTER CONFIRMATION", "allowed")}
            <div class="proposal">Supersede R-014</div>
            <div class="detail">RESULTING STATE · <b>SUPERSEDED</b><br>
            REVIEWER ACTION REQUIRED</div>""",
        )
        action_1, action_2 = st.columns(2)
        action_1.button(
            "Confirm",
            disabled=True,
            use_container_width=True,
            help="Available after persistence is connected.",
        )
        action_2.button("Reject", disabled=True, use_container_width=True)


def _render_register() -> None:
    confirmed, transition, archive = st.columns(3, gap="large")
    with confirmed:
        _panel(
            "CONFIRMED SCOPE",
            "Current register heads",
            f"""{_status("CONFIRMED", "allowed")}
            <div class="proposal">R-021 · Retain audit logs for 90 days</div>
            <div class="detail">VERSION 02 · refined in Meeting 02</div>""",
        )
    with transition:
        _panel(
            "AWAITING DECISION",
            "No state mutation yet",
            f"""{_status("PENDING", "pending")}
            <div class="proposal">R-014 · Identity access pathway</div>
            <div class="detail">PROPOSAL P-003 · evidence linked to Meeting 02</div>""",
        )
    with archive:
        _panel(
            "RETAINED HISTORY",
            "Never hidden by an update",
            f"""{_status("SUPERSEDED", "archived")}
            <div class="proposal">R-009 · Legacy self-service reset</div>
            <div class="detail">VERSION 01 · preserved for traceability</div>""",
        )


def _render_decision_trace() -> None:
    left, right = st.columns((1.35, 1), gap="large")
    with left:
        _panel(
            "EVENT STREAM",
            "Append-only audit view · preview",
            """<div class="trace-row"><span class="trace-dot violet"></span> M01 · Confirmed R-014 · email/password access</div>
            <div class="trace-row"><span class="trace-dot green"></span> M02 · Evidence validated · Turn 018</div>
            <div class="trace-row"><span class="trace-dot"></span> M02 · Proposal P-003 · awaiting reviewer decision</div>""",
        )
    with right:
        _panel(
            "PIPELINE POSITION",
            "Static deployment map",
            """<div class="wireframe">INGEST → EXTRACT → VALIDATE<br>
            → RETRIEVE → CLASSIFY<br>→ ENGINE → <b>REVIEW</b> → COMMIT</div>
            <div class="detail" style="margin-top:.85rem;">This interface is the human gate between deterministic validation and register mutation.</div>""",
        )


def main() -> None:
    """Render a local-only, read-only operations homepage."""
    st.set_page_config(page_title="CIA // Requirement Ops", page_icon="◈", layout="wide")
    _apply_theme()
    _render_sidebar()
    st.markdown(
        '<p class="eyebrow">Requirement lifecycle command center</p>', unsafe_allow_html=True
    )
    st.markdown(
        """<section class="hero"><h1>Scope changes, under control.</h1>
        <p>Inspect the evidence, validate the transition, then let an authorised reviewer decide what becomes agreed scope.</p>
        <div class="hero-signal">● SYSTEM STATUS / PREVIEW READY &nbsp;&nbsp; ◇ REGISTER WRITES / HUMAN-GATED</div></section>""",
        unsafe_allow_html=True,
    )
    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("CONFIRMED REQUIREMENTS", "12")
    metric_2.metric("PENDING PROPOSALS", "3")
    metric_3.metric("ENGINE GUARDS", "100%")
    metric_4.metric("EVIDENCE LINKED", "100%")
    st.caption(
        "LOCAL PREVIEW DATA ONLY · figures and records are illustrative until the pipeline is connected."
    )
    review_tab, register_tab, trace_tab = st.tabs(
        ["⌁  Review queue", "◫  Requirements register", "◎  Decision trace"]
    )
    with review_tab:
        _render_review_queue()
    with register_tab:
        _render_register()
    with trace_tab:
        _render_decision_trace()


if __name__ == "__main__":
    main()
