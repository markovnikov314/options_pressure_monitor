"""
Real-time console visualization for the options pressure monitor.
"""
from datetime import datetime
import os
from pathlib import Path
from typing import Dict, List

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pressure_analyzer import PressureAnalysis


class Visualizer:
    """Rich terminal dashboard plus PNG screenshot export."""

    def __init__(self, clear_screen: bool = True):
        self.console = Console()
        self.clear_screen = clear_screen

    def create_pressure_bar(self, score: float, width: int = 18) -> Text:
        filled = int(max(0, min(score, 100)) / 100 * width)
        if score >= 75:
            color = "bright_red"
        elif score >= 60:
            color = "yellow"
        elif score >= 45:
            color = "bright_green"
        else:
            color = "cyan"

        bar = Text()
        bar.append("#" * filled, style=color)
        bar.append("-" * (width - filled), style="dim")
        return bar

    def create_strike_table(
        self, analyses: List[PressureAnalysis], option_type: str, atm_strike: float
    ) -> Table:
        title = f"{'CALL' if option_type == 'CE' else 'PUT'} Pressure Map"
        table = Table(title=title, box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Strike", justify="right", width=8)
        table.add_column("Pressure", justify="left", width=20)
        table.add_column("Score", justify="right", width=7)
        table.add_column("Chg", justify="right", width=7)
        table.add_column("OI%", justify="right", width=7)
        table.add_column("Px%", justify="right", width=7)
        table.add_column("IV", justify="right", width=6)
        table.add_column("Signal", justify="left", width=13)

        for analysis in sorted(analyses, key=lambda item: item.strike, reverse=True):
            strike = Text(f"{int(analysis.strike)}")
            if analysis.strike == atm_strike:
                strike.stylize("bold green")
            elif analysis.is_pressure_leader:
                strike.stylize("bold yellow")

            score = analysis.pressure_score
            score_style = "bright_red" if score >= 75 else "yellow" if score >= 60 else "cyan"
            change = self._fmt_change(analysis.pressure_change)
            oi_pct = self._fmt_change(analysis.oi_change_pct)
            price_pct = self._fmt_change(analysis.price_change_pct)
            signal = self._short_signal(analysis.signal)
            if analysis.strike == atm_strike:
                signal = f"ATM {signal}"
            if analysis.is_pressure_leader:
                signal = f"LEAD {signal}"
            if analysis.leader_shifted:
                signal = f"SHIFT {signal}"

            table.add_row(
                strike,
                self.create_pressure_bar(score),
                Text(f"{score:.1f}", style=score_style),
                change,
                oi_pct,
                price_pct,
                f"{self._normalized_iv(analysis.iv):.1f}",
                signal,
            )

        return table

    def create_header(
        self,
        spot_price: float,
        atm_strike: float,
        expiry: str,
        update_count: int,
        snapshot_count: int = 0,
    ) -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header = Text()
        header.append("NIFTY Options Pressure Monitor", style="bold white")
        header.append("\n\nSpot: ", style="dim")
        header.append(f"{spot_price:.2f}", style="bold green")
        header.append("  |  ATM: ", style="dim")
        header.append(f"{int(atm_strike)}", style="bold cyan")
        header.append("  |  Expiry: ", style="dim")
        header.append(expiry, style="bold yellow")
        header.append(f"\n\nLast Update: {now}", style="dim")
        header.append(f"  |  Updates: {update_count}", style="dim")
        header.append(f"  |  Snapshots: {snapshot_count}", style="dim cyan")
        return Panel(header, border_style="blue", box=box.DOUBLE)

    def create_alerts_panel(self, alerts: List[Dict]) -> Panel:
        if not alerts:
            return Panel(Text("No pressure alerts", style="dim"), title="Alerts", border_style="yellow")

        lines = []
        for alert in alerts[:6]:
            alert_type = alert.get("type", "")
            strike = int(alert.get("strike", 0))
            option_type = alert.get("option_type", "")
            score = alert.get("pressure_score", 0)
            change = alert.get("pressure_change")
            signal = alert.get("signal", "")

            if alert_type == "HOT_CONTRACT":
                style = "bright_red"
                message = f"HOT: {strike} {option_type} score {score:.1f} ({signal})"
            elif alert_type == "PRESSURE_SPIKE":
                style = "yellow"
                message = f"SPIKE: {strike} {option_type} pressure {change:+.1f} -> {score:.1f}"
            elif alert_type == "PRESSURE_FADE":
                style = "red"
                message = f"FADE: {strike} {option_type} pressure {change:+.1f} -> {score:.1f}"
            elif alert_type == "LEADER_SHIFT":
                style = "cyan"
                message = f"SHIFT: leader moved to {strike} {option_type} ({score:.1f})"
            else:
                style = "white"
                message = str(alert)
            lines.append(Text(message, style=style))

        return Panel(Text("\n").join(lines), title="Alerts", border_style="yellow")

    def create_summary_panel(
        self, call_analyses: List[PressureAnalysis], put_analyses: List[PressureAnalysis]
    ) -> Panel:
        top_call = max(call_analyses, key=lambda item: item.pressure_score, default=None)
        top_put = max(put_analyses, key=lambda item: item.pressure_score, default=None)

        content = Text()
        if top_call:
            content.append("Top call pressure: ", style="dim")
            content.append(
                f"{int(top_call.strike)} CE {top_call.pressure_score:.1f} ({top_call.signal})\n",
                style="bold green",
            )
        if top_put:
            content.append("Top put pressure:  ", style="dim")
            content.append(
                f"{int(top_put.strike)} PE {top_put.pressure_score:.1f} ({top_put.signal})\n",
                style="bold magenta",
            )

        if top_call and top_put:
            spread = top_call.pressure_score - top_put.pressure_score
            bias = "Call-side pressure leads" if spread > 5 else "Put-side pressure leads" if spread < -5 else "Pressure is balanced"
            content.append("\nRead: ", style="dim")
            content.append(f"{bias} ({spread:+.1f})", style="bold cyan")

        return Panel(content or Text("Waiting for enough data", style="dim"), title="Pressure Read", border_style="green")

    def render_dashboard(
        self,
        call_analyses: List[PressureAnalysis],
        put_analyses: List[PressureAnalysis],
        alerts: List[Dict],
        spot_price: float,
        atm_strike: float,
        expiry: str,
        update_count: int,
        snapshot_count: int = 0,
    ):
        if self.clear_screen:
            os.system("cls" if os.name == "nt" else "clear")

        self.console.print(
            self.create_header(
                spot_price, atm_strike, expiry, update_count, snapshot_count
            )
        )
        self.console.print()
        self.console.print(
            Columns(
                [
                    self.create_strike_table(call_analyses, "CE", atm_strike),
                    self.create_strike_table(put_analyses, "PE", atm_strike),
                ],
                equal=True,
                expand=True,
            )
        )
        self.console.print()
        self.console.print(self.create_alerts_panel(alerts))
        self.console.print()
        self.console.print(self.create_summary_panel(call_analyses, put_analyses))
        self.console.print()
        self.console.print("[dim]Press Ctrl+C to stop monitoring[/dim]", justify="center")

    def save_screenshot(
        self,
        path: str,
        call_analyses: List[PressureAnalysis],
        put_analyses: List[PressureAnalysis],
        alerts: List[Dict],
        spot_price: float,
        atm_strike: float,
        expiry: str,
        update_count: int,
        snapshot_count: int = 0,
    ) -> Path:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise RuntimeError("Pillow is required for screenshot export") from exc

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)

        width, height = 1600, 1280
        image = Image.new("RGB", (width, height), "#0b1020")
        draw = ImageDraw.Draw(image)
        mono, mono_small, mono_bold, mono_title = self._load_fonts(ImageFont)

        def put(x: int, y: int, value: str, fill: str = "#d8dee9", font=None):
            draw.text((x, y), value, font=font or mono, fill=fill)

        draw.rounded_rectangle((34, 32, width - 34, height - 32), radius=18, fill="#111827", outline="#253044", width=2)
        draw.rectangle((34, 32, width - 34, 92), fill="#151f32")
        for index, color in enumerate(["#ff5f57", "#ffbd2e", "#28c840"]):
            draw.ellipse((66 + index * 34, 55, 84 + index * 34, 73), fill=color)
        put(172, 54, "PowerShell - options_pressure_monitor", "#a8b3cf", mono_small)

        y = 122
        put(76, y, "NIFTY Options Pressure Monitor", "#ffffff", mono_title)
        y += 68

        draw.rounded_rectangle((76, y, width - 76, y + 138), radius=8, fill="#0f172a", outline="#38bdf8", width=2)
        put(102, y + 22, "NIFTY Options Pressure Monitor", "#f8fafc", mono_bold)
        put(102, y + 66, f"Spot: {spot_price:.2f}  |  ATM: {int(atm_strike)}  |  Expiry: {expiry}", "#86efac", mono)
        put(102, y + 102, f"Session: 2026-04-28 15:20 IST  |  Updates: {update_count}  |  Snapshots: {snapshot_count}", "#c4b5fd", mono_small)
        y += 174

        left = (76, y, 760, y + 420)
        right = (840, y, width - 76, y + 420)
        self._draw_screenshot_table(draw, left, "CALL Pressure Map", call_analyses, atm_strike, mono_small, mono_bold)
        self._draw_screenshot_table(draw, right, "PUT Pressure Map", put_analyses, atm_strike, mono_small, mono_bold)
        y += 458

        draw.rounded_rectangle((76, y, width - 76, y + 150), radius=8, fill="#0f172a", outline="#facc15", width=2)
        put(102, y + 20, "Alerts", "#facc15", mono_bold)
        if alerts:
            for idx, alert in enumerate(alerts[:3]):
                strike = int(alert.get("strike", 0))
                option_type = alert.get("option_type", "")
                score = alert.get("pressure_score", 0)
                signal = alert.get("signal", "")
                put(102, y + 62 + idx * 30, f"{alert.get('type')}: {strike} {option_type} score {score:.1f} ({signal})", "#fde68a", mono_small)
        else:
            put(102, y + 64, "No pressure alerts", "#94a3b8", mono_small)
        y += 184

        top_call = max(call_analyses, key=lambda item: item.pressure_score, default=None)
        top_put = max(put_analyses, key=lambda item: item.pressure_score, default=None)
        draw.rounded_rectangle((76, y, width - 76, y + 116), radius=8, fill="#0f172a", outline="#22c55e", width=2)
        put(102, y + 20, "Pressure Read", "#86efac", mono_bold)
        if top_call and top_put:
            spread = top_call.pressure_score - top_put.pressure_score
            put(102, y + 62, f"Top CE: {int(top_call.strike)} {top_call.pressure_score:.1f}  |  Top PE: {int(top_put.strike)} {top_put.pressure_score:.1f}  |  Spread: {spread:+.1f}", "#d8dee9", mono_small)
        y += 150

        put(76, y, "Composite score blends activity, OI change, price trend, IV, and spread quality.", "#94a3b8", mono_small)

        image.save(out)
        return out

    def print_startup_message(self, expiry: str):
        self.console.print()
        self.console.print(
            Panel(
                "[bold green]Options Pressure Monitor Starting...[/bold green]\n\n"
                f"Index: NIFTY 50\n"
                f"Expiry: {expiry}\n"
                f"Mode: Upstox live feed\n"
                f"Update Interval: 20 seconds\n"
                f"Lookback: 10 periods\n\n"
                "[dim]Waiting for first pressure read...[/dim]",
                title="Initializing",
                border_style="green",
            )
        )
        self.console.print()

    def print_error(self, message: str):
        self.console.print(f"[bold red]Error:[/bold red] {message}")

    def print_info(self, message: str):
        self.console.print(f"[bold blue]Info:[/bold blue] {message}")

    def _fmt_change(self, value: float | None) -> Text:
        if value is None:
            return Text("--", style="dim")
        style = "green" if value > 0 else "red" if value < 0 else "dim"
        return Text(f"{value:+.1f}", style=style)

    def _normalized_iv(self, iv: float | None) -> float:
        if iv is None:
            return 0
        iv_value = float(iv)
        return iv_value * 100 if iv_value <= 1 else iv_value

    def _load_fonts(self, image_font):
        font_paths = [
            r"C:\Windows\Fonts\CascadiaMono.ttf",
            r"C:\Windows\Fonts\CascadiaMonoPL.ttf",
            r"C:\Windows\Fonts\consola.ttf",
        ]
        for font_path in font_paths:
            if Path(font_path).exists():
                return (
                    image_font.truetype(font_path, 24),
                    image_font.truetype(font_path, 20),
                    image_font.truetype(font_path, 28),
                    image_font.truetype(font_path, 30),
                )
        fallback = image_font.load_default()
        return fallback, fallback, fallback, fallback

    def _draw_screenshot_table(
        self,
        draw,
        box_area,
        title: str,
        analyses: List[PressureAnalysis],
        atm_strike: float,
        mono_small,
        mono_bold,
    ):
        x1, y1, x2, y2 = box_area
        accent = "#22c55e" if "CALL" in title else "#f97316"
        draw.rounded_rectangle(box_area, radius=8, fill="#0f172a", outline=accent, width=2)
        draw.text((x1 + 24, y1 + 20), title, font=mono_bold, fill="#ffffff")
        draw.text((x1 + 24, y1 + 66), "Strike   Score   Chg    OI%    Signal        Bar", font=mono_small, fill="#93c5fd")

        rows = sorted(analyses, key=lambda item: item.strike, reverse=True)[:7]
        row_y = y1 + 106
        for analysis in rows:
            status = self._short_signal(analysis.signal)
            if analysis.strike == atm_strike:
                status = "ATM " + status
            elif analysis.is_pressure_leader:
                status = "LEAD " + status

            score = analysis.pressure_score
            color = "#fca5a5" if score >= 75 else "#fde68a" if score >= 60 else "#86efac"
            change = "--" if analysis.pressure_change is None else f"{analysis.pressure_change:+.1f}"
            oi_pct = "--" if analysis.oi_change_pct is None else f"{analysis.oi_change_pct:+.1f}"
            draw.text((x1 + 24, row_y), f"{int(analysis.strike):>5}   {score:>5.1f}  {change:>5}  {oi_pct:>5}  {status[:12]:<12}", font=mono_small, fill=color)

            bar_x = x1 + 534
            bar_y = row_y + 7
            draw.rectangle((bar_x, bar_y, bar_x + 124, bar_y + 15), fill="#1e293b")
            bar_width = int(score / 100 * 124)
            draw.rectangle((bar_x, bar_y, bar_x + bar_width, bar_y + 15), fill="#38bdf8")
            row_y += 42

    def _short_signal(self, signal: str) -> str:
        return {
            "LONG_BUILDUP": "LONG",
            "SHORT_BUILDUP": "SHORT",
            "SHORT_COVER": "COVER",
            "LONG_UNWIND": "UNWIND",
            "HOT_FLOW": "HOT",
        }.get(signal, signal)
