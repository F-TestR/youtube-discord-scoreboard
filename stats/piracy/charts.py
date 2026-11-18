"""Chart images for Discord (Discord can't draw charts, so we send PNGs)."""
import datetime as dt
import io

from . import util

COLORS = {"youtube": "#FF6B6B", "tiktok": "#2EC4B6", "instagram": "#C792EA", "discord": "#8EA1FF"}
BG, PANEL, GRID, INK, MUTED, GOLD = "#0B1520", "#0F1E2C", "#1C3142", "#E8EEF2", "#93A7B4", "#E3B04B"


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import dates as mdates
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID,
                         "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                         "text.color": INK, "axes.facecolor": PANEL, "figure.facecolor": BG})
    return plt, mdates


def _fmt_axis(ax, mdates):
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.grid(axis="x", visible=False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)
    ax.yaxis.set_major_formatter(lambda v, _: util.fmt_short(v))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %-d", tz=util.UK))


def scoreboard(panels, now, days=7):
    """panels: [{platform, series:[(iso, total)], uploads:[(iso, title)], gain_24h, total}] -> PNG bytes"""
    plt, mdates = _mpl()
    panels = [p for p in panels if any(v is not None for _, v in p["series"])] or panels[:1]
    n = max(len(panels), 1)
    fig, axes = plt.subplots(1, n, figsize=(12, 4.6), dpi=110, squeeze=False)
    start = now - dt.timedelta(days=days)
    for ax, p in zip(axes[0], panels):
        col = COLORS.get(p["platform"], GOLD)
        xs = [util.parse(t) for t, v in p["series"] if v is not None and util.parse(t) >= start]
        ys = [v for t, v in p["series"] if v is not None and util.parse(t) >= start]
        _fmt_axis(ax, mdates)
        if xs:
            ax.fill_between(xs, ys, color=col, alpha=0.16, linewidth=0)
            ax.plot(xs, ys, color=col, linewidth=2.6, solid_capstyle="round")
            ax.scatter([xs[-1]], [ys[-1]], s=46, color=col, zorder=5, edgecolor=BG, linewidth=2)
            lo = min(ys)
            ax.set_ylim(max(0, lo - (max(ys) - lo) * 0.25 - 1), max(ys) * 1.12 + 1)
            for t, title in p.get("uploads", []):
                tt = util.parse(t)
                if tt >= start and tt <= now:
                    ax.axvline(tt, color=GOLD, linewidth=1, linestyle=(0, (2, 3)), alpha=0.8)
                    ax.text(tt, ax.get_ylim()[1] * 0.985, " new", color=GOLD, fontsize=9, va="top", ha="left")
        ax.set_xlim(start, now + dt.timedelta(hours=3))
        g = p.get("gain_24h")
        head = util.NAMES[p["platform"]]
        ax.set_title(head, loc="left", fontsize=14, fontweight="bold", color=INK, pad=26)
        sub = f"{util.fmt_int(p.get('total'))} views"
        if g is not None:
            sub += f"   {util.fmt_signed(g)} in 24 h"
        ax.text(0, 1.03, sub, transform=ax.transAxes, color=col, fontsize=11.5, fontweight="bold")
        if not xs:
            ax.text(0.5, 0.5, "Not connected yet" if p.get("status") != "ok" else "No data yet",
                    transform=ax.transAxes, ha="center", va="center", color=MUTED, fontsize=13)
            ax.set_yticks([])
    fig.text(0.995, 0.012, f"Total views on live posts · last {days} days · updated {util.uk(now):%a %-d %b %H:%M} UK",
             ha="right", va="bottom", color=MUTED, fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 1), w_pad=3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def weekly(daily_by_platform, now):
    """Bars of views gained per day for the last 7 days, one group per day. PNG bytes."""
    plt, mdates = _mpl()
    fig, ax = plt.subplots(figsize=(12, 4.4), dpi=110)
    plats = [pl for pl, rows in daily_by_platform.items() if any(v for _, v in rows[-7:])]
    width = 0.8 / max(len(plats), 1)
    days = [d for d, _ in next(iter(daily_by_platform.values()), [])[-7:]]
    for i, pl in enumerate(plats):
        rows = dict(daily_by_platform[pl][-7:])
        xs = [k + i * width - 0.4 + width / 2 for k in range(len(days))]
        ys = [rows.get(d) or 0 for d in days]
        bars = ax.bar(xs, ys, width=width * 0.92, color=COLORS[pl], label=util.NAMES[pl])
        for b, v in zip(bars, ys):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height(), util.fmt_short(v), ha="center",
                        va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(days)))
    ax.set_xticklabels([dt.date.fromisoformat(d).strftime("%a %-d") for d in days])
    ax.grid(axis="y", color=GRID)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.yaxis.set_major_formatter(lambda v, _: util.fmt_short(v))
    ax.set_title("Views gained each day", loc="left", fontsize=14, fontweight="bold", pad=12)
    if plats:
        ax.legend(frameon=False, loc="upper left", ncol=3, labelcolor=INK, bbox_to_anchor=(0, 1.0))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
