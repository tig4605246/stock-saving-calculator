#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 存股計畫 — 圖形化計算器
Author: ChatGPT
Description:
    以 Tkinter + Matplotlib 實作的多頁籤 GUI，涵蓋以下功能：
    1) 定期定額累積試算（含期初/期末投入、初始本金）
    2) 目標反推每月投入金額
    3) 股息試算與領息目標反推
    4) 生命週期：累積至退休 + 退休提領（固定年期或安全提領率SWR）
    5) 投資組合試算（權重、期望報酬、加權殖利率、成長曲線、圓餅圖）
    6) 情境參數（較差/穩定/歷史/較佳）的一鍵套用

Finance formulas (monthly compounding, end-of-period unless specified):
- FV of a series (ordinary annuity): FV_series = PMT * ((1+i)^n - 1) / i
- FV of a series (annuity-due, begin): FV_series_due = PMT * ((1+i)^n - 1) / i * (1+i)
- FV with initial principal: FV = PV*(1+i)^n + FV_series[(_due)]
- Solve PMT to reach target FV: PMT = (FV_target - PV*(1+i)^n) / factor
  where factor = ((1+i)^n - 1)/i * (1+i if due else 1)
- Dividend income (monthly): income = principal * dividend_yield / 12
- Required principal for target dividend: principal = target_monthly * 12 / dividend_yield
- Retirement withdrawal (fixed years, ordinary annuity): 
  monthly_withdraw = corpus * j / (1 - (1+j)^(-m)), where j is monthly return, m months.
- SWR monthly: corpus * swr / 12

Notes:
- 報酬率輸入以「年化」為單位（百分比），程式自動換算成月複利： i = (1+r_annual)^(1/12)-1
- 殖利率輸入以「年化％」。

License: MIT
"""
from __future__ import annotations

import math
import csv
from dataclasses import dataclass
from typing import List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from matplotlib import rcParams, font_manager
import os
from pathlib import Path

def _configure_cjk_font():
    # 1) 環境變數可直接指定字型檔（建議 Noto/思源系列 .ttf/.otf）
    env_font = os.getenv("MPL_CJK_FONT")
    if env_font and Path(env_font).exists():
        font_manager.fontManager.addfont(env_font)          # 於執行期註冊字型檔（不會寫入快取）
        from matplotlib.font_manager import FontProperties
        rc_name = FontProperties(fname=env_font).get_name() # 取得字型名稱做為 family
        rcParams["font.family"] = ["sans-serif"]
        rcParams["font.sans-serif"] = [rc_name] + list(rcParams.get("font.sans-serif", []))

    # 2) 否則從常見 CJK 名稱中，挑第一個系統已安裝者
    candidates = [
        "Noto Sans CJK TC","Noto Sans TC","Source Han Sans TC",   # Cross-platform / 繁中
        "Microsoft JhengHei","PMingLiU",                          # Windows
        "PingFang TC","Heiti TC","LiHei Pro",                     # macOS
        "WenQuanYi Zen Hei",                                      # Linux 常見
        "Arial Unicode MS","SimHei"                               # 廣字元備援
    ]
    try:
        installed = {f.name for f in font_manager.fontManager.ttflist}
        chosen = next((c for c in candidates if c in installed), None)
        if chosen:
            rcParams["font.family"] = ["sans-serif"]
            rcParams["font.sans-serif"] = [chosen] + list(rcParams.get("font.sans-serif", []))
    except Exception:
        pass

    # 3) 修正負號顯示（避免被選字型缺 U+2212 時顯示為方框）
    rcParams["axes.unicode_minus"] = False

_configure_cjk_font()

# ---------- Financial math helpers ----------

def annual_to_monthly_rate(r_annual_pct: float) -> float:
    """Convert annual CAGR % to effective monthly rate, i = (1+r)^(1/12)-1."""
    r = r_annual_pct / 100.0
    return (1.0 + r) ** (1.0 / 12.0) - 1.0


def fv_annuity(pmt: float, i: float, n: int, due: bool = False) -> float:
    """Future value of an annuity, monthly compounding.
    due=True means annuity-due (deposit at period start)."""
    if i == 0:
        fv = pmt * n
    else:
        fv = pmt * ((1 + i) ** n - 1) / i
    if due:
        fv *= (1 + i)
    return fv


def fv_with_principal(pv: float, pmt: float, i: float, n: int, due: bool = False) -> float:
    return pv * (1 + i) ** n + fv_annuity(pmt, i, n, due)


def solve_pmt_for_target_fv(fv_target: float, pv: float, i: float, n: int, due: bool = False) -> float:
    factor = n if i == 0 else ((1 + i) ** n - 1) / i
    if due and i != 0:
        factor *= (1 + i)
    # subtract FV of principal growth
    numer = fv_target - pv * (1 + i) ** n
    if abs(factor) < 1e-12:
        raise ValueError("因子過小，無法反推每月投入。請調整參數。")
    return numer / factor


def monthly_dividend_income(principal: float, dividend_yield_pct: float) -> float:
    y = dividend_yield_pct / 100.0
    return principal * y / 12.0


def required_principal_for_dividend(target_monthly: float, dividend_yield_pct: float) -> float:
    y = dividend_yield_pct / 100.0
    if y <= 0:
        raise ValueError("殖利率需大於 0。")
    return target_monthly * 12.0 / y


def monthly_withdraw_for_years(corpus: float, annual_return_pct: float, years: float) -> float:
    """Fixed-term retirement withdrawal (ordinary annuity)."""
    j = annual_to_monthly_rate(annual_return_pct)
    m = int(round(years * 12))
    if m <= 0:
        raise ValueError("退休年期需大於 0。")
    if j == 0:
        return corpus / m
    return corpus * j / (1 - (1 + j) ** (-m))


def swr_monthly(corpus: float, swr_pct: float) -> float:
    return corpus * (swr_pct / 100.0) / 12.0


def simulate_growth(pv: float, pmt: float, i: float, months: int, due: bool = False) -> List[float]:
    """Return list of balances each month (length months+1, including t=0)."""
    balances = [pv]
    bal = pv
    for t in range(1, months + 1):
        if due:
            # deposit at start
            bal += pmt
            bal *= (1 + i)
        else:
            # deposit at end
            bal *= (1 + i)
            bal += pmt
        balances.append(bal)
    return balances


def simulate_drawdown(corpus: float, monthly_withdraw: float, annual_return_pct: float, months: int) -> List[float]:
    """Balance path during retirement withdrawals (end-of-month withdraw)."""
    j = annual_to_monthly_rate(annual_return_pct)
    balances = [corpus]
    bal = corpus
    for _ in range(months):
        # grow for month, then withdraw at end
        bal *= (1 + j)
        bal -= monthly_withdraw
        balances.append(max(bal, 0.0))
        if bal <= 0:
            break
    return balances


# ---------- Tkinter UI ----------

class PlotArea:
    def __init__(self, parent: tk.Widget, width=6, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.toolbar = NavigationToolbar2Tk(self.canvas, parent, pack_toolbar=False)
        self.toolbar.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

    def plot_series(self, xs, ys, title: str, xlabel: str, ylabel: str):
        self.ax.clear()
        self.ax.plot(xs, ys)
        self.ax.set_title(title)
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, alpha=0.3)
        self.canvas.draw()

    def plot_two_series(self, xs, ys1, ys2, labels: Tuple[str, str], title: str, xlabel: str, ylabel: str):
        self.ax.clear()
        self.ax.plot(xs, ys1, label=labels[0])
        self.ax.plot(xs, ys2, label=labels[1])
        self.ax.set_title(title)
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.legend()
        self.ax.grid(True, alpha=0.3)
        self.canvas.draw()

    def plot_pie(self, labels, sizes, title: str):
        self.ax.clear()
        self.ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
        self.ax.axis('equal')
        self.ax.set_title(title)
        self.canvas.draw()


class ETFCalculatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ETF 存股計畫 — 計算器")
        self.geometry("1200x780")
        self._init_style()

        self.scenarios = {
            "較差": {"return": 3.0, "div_yield": 2.0},
            "穩定": {"return": 5.0, "div_yield": 2.5},
            "歷史": {"return": 7.0, "div_yield": 3.0},
            "較佳": {"return": 9.0, "div_yield": 3.5},
        }

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_dca = ttk.Frame(notebook)
        self.tab_goal = ttk.Frame(notebook)
        self.tab_div = ttk.Frame(notebook)
        self.tab_life = ttk.Frame(notebook)
        self.tab_port = ttk.Frame(notebook)
        self.tab_scn = ttk.Frame(notebook)

        notebook.add(self.tab_dca, text="定期定額")
        notebook.add(self.tab_goal, text="目標反推")
        notebook.add(self.tab_div, text="股息/領息目標")
        notebook.add(self.tab_life, text="生命週期")
        notebook.add(self.tab_port, text="投資組合")
        notebook.add(self.tab_scn, text="情境")

        self._build_tab_dca()
        self._build_tab_goal()
        self._build_tab_div()
        self._build_tab_life()
        self._build_tab_port()
        self._build_tab_scn()

    def _init_style(self):
        style = ttk.Style(self)
        # Try using a platform-available theme
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    # ----- Tab: DCA -----
    def _build_tab_dca(self):
        frm = self.tab_dca
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=2)
        frm.rowconfigure(0, weight=1)

        # Left: inputs
        left = ttk.Frame(frm, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        for i in range(12):
            left.rowconfigure(i, weight=0)
        left.columnconfigure(1, weight=1)

        self.dca_pv = tk.DoubleVar(value=0.0)
        self.dca_pmt = tk.DoubleVar(value=10000.0)
        self.dca_return = tk.DoubleVar(value=7.0)
        self.dca_years = tk.IntVar(value=20)
        self.dca_due = tk.BooleanVar(value=False)

        ttk.Label(left, text="初始本金 (元)").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.dca_pv).grid(row=0, column=1, sticky="ew")

        ttk.Label(left, text="每月投入 (元)").grid(row=1, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.dca_pmt).grid(row=1, column=1, sticky="ew")

        ttk.Label(left, text="年化報酬率 (%)").grid(row=2, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.dca_return).grid(row=2, column=1, sticky="ew")

        ttk.Label(left, text="投資年數 (年)").grid(row=3, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.dca_years).grid(row=3, column=1, sticky="ew")

        ttk.Checkbutton(left, text="期初投入（每月開頭）", variable=self.dca_due).grid(row=4, column=0, columnspan=2, sticky="w")

        ttk.Button(left, text="計算 & 繪圖", command=self.on_dca_calc).grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(left, text="匯出 CSV", command=self.on_dca_export).grid(row=6, column=0, columnspan=2, sticky="ew")

        self.dca_result = ttk.Label(left, text="", foreground="#1a7f37", wraplength=360, justify="left")
        self.dca_result.grid(row=7, column=0, columnspan=2, sticky="w", pady=8)

        # Right: plot
        right = ttk.Frame(frm)
        right.grid(row=0, column=1, sticky="nsew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        self.dca_plot = PlotArea(right)

    def on_dca_calc(self):
        try:
            i = annual_to_monthly_rate(self.dca_return.get())
            months = max(0, int(self.dca_years.get()) * 12)
            due = self.dca_due.get()
            balances = simulate_growth(self.dca_pv.get(), self.dca_pmt.get(), i, months, due)
            xs = list(range(len(balances)))
            self.dca_plot.plot_series(xs, balances, "定期定額累積曲線", "月份", "總資產 (元)")
            fv = balances[-1]
            total_contrib = self.dca_pv.get() + self.dca_pmt.get() * months
            msg = f"期末資產：約 {fv:,.0f} 元；總投入：約 {total_contrib:,.0f} 元；累積報酬：約 {fv - total_contrib:,.0f} 元"
            self.dca_result.config(text=msg)
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    def on_dca_export(self):
        try:
            i = annual_to_monthly_rate(self.dca_return.get())
            months = max(0, int(self.dca_years.get()) * 12)
            due = self.dca_due.get()
            balances = simulate_growth(self.dca_pv.get(), self.dca_pmt.get(), i, months, due)
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], title="匯出累積明細")
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["month", "balance"])
                for m, bal in enumerate(balances):
                    w.writerow([m, f"{bal:.2f}"])
            messagebox.showinfo("完成", f"已匯出：{path}")
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ----- Tab: Goal Seek -----
    def _build_tab_goal(self):
        frm = self.tab_goal
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=2)

        left = ttk.Frame(frm, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        for i in range(12):
            left.rowconfigure(i, weight=0)
        left.columnconfigure(1, weight=1)

        self.goal_target = tk.DoubleVar(value=5_000_000.0)
        self.goal_pv = tk.DoubleVar(value=0.0)
        self.goal_return = tk.DoubleVar(value=7.0)
        self.goal_years = tk.IntVar(value=20)
        self.goal_due = tk.BooleanVar(value=False)

        ttk.Label(left, text="目標金額 (元)").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.goal_target).grid(row=0, column=1, sticky="ew")
        ttk.Label(left, text="初始本金 (元)").grid(row=1, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.goal_pv).grid(row=1, column=1, sticky="ew")
        ttk.Label(left, text="年化報酬率 (%)").grid(row=2, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.goal_return).grid(row=2, column=1, sticky="ew")
        ttk.Label(left, text="投資年數 (年)").grid(row=3, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.goal_years).grid(row=3, column=1, sticky="ew")
        ttk.Checkbutton(left, text="期初投入", variable=self.goal_due).grid(row=4, column=0, columnspan=2, sticky="w")

        ttk.Button(left, text="反推每月投入", command=self.on_goal_calc).grid(row=5, column=0, columnspan=2, sticky="ew")

        self.goal_result = ttk.Label(left, text="", foreground="#1a7f37", wraplength=360, justify="left")
        self.goal_result.grid(row=6, column=0, columnspan=2, sticky="w", pady=8)

        right = ttk.Frame(frm)
        right.grid(row=0, column=1, sticky="nsew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        self.goal_plot = PlotArea(right)

    def on_goal_calc(self):
        try:
            i = annual_to_monthly_rate(self.goal_return.get())
            n = max(0, int(self.goal_years.get()) * 12)
            pmt = solve_pmt_for_target_fv(self.goal_target.get(), self.goal_pv.get(), i, n, self.goal_due.get())
            self.goal_result.config(text=f"為達成目標，需每月投入：約 {pmt:,.0f} 元")
            # 同步畫出對應的累積路徑
            balances = simulate_growth(self.goal_pv.get(), pmt, i, n, self.goal_due.get())
            xs = list(range(len(balances)))
            self.goal_plot.plot_series(xs, balances, "達標對應的累積曲線", "月份", "總資產 (元)")
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ----- Tab: Dividend -----
    def _build_tab_div(self):
        frm = self.tab_div
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # Left block: income from principal
        left = ttk.LabelFrame(frm, text="由本金推算每月股息", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        left.columnconfigure(1, weight=1)

        self.div_principal = tk.DoubleVar(value=1_000_000.0)
        self.div_yield = tk.DoubleVar(value=3.0)
        ttk.Label(left, text="本金 (元)").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.div_principal).grid(row=0, column=1, sticky="ew")
        ttk.Label(left, text="年化殖利率 (%)").grid(row=1, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.div_yield).grid(row=1, column=1, sticky="ew")
        ttk.Button(left, text="計算每月股息", command=self.on_div_income).grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        self.div_income_result = ttk.Label(left, text="", foreground="#1a7f37")
        self.div_income_result.grid(row=3, column=0, columnspan=2, sticky="w")

        # Right block: principal needed for target income
        right = ttk.LabelFrame(frm, text="由目標月股息反推所需本金", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        right.columnconfigure(1, weight=1)

        self.div_target_monthly = tk.DoubleVar(value=20_000.0)
        self.div_yield2 = tk.DoubleVar(value=3.0)
        ttk.Label(right, text="目標月股息 (元)").grid(row=0, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.div_target_monthly).grid(row=0, column=1, sticky="ew")
        ttk.Label(right, text="年化殖利率 (%)").grid(row=1, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.div_yield2).grid(row=1, column=1, sticky="ew")
        ttk.Button(right, text="反推所需本金", command=self.on_div_required).grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        self.div_required_result = ttk.Label(right, text="", foreground="#1a7f37")
        self.div_required_result.grid(row=3, column=0, columnspan=2, sticky="w")

    def on_div_income(self):
        try:
            income = monthly_dividend_income(self.div_principal.get(), self.div_yield.get())
            self.div_income_result.config(text=f"約每月股息：{income:,.0f} 元")
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    def on_div_required(self):
        try:
            principal = required_principal_for_dividend(self.div_target_monthly.get(), self.div_yield2.get())
            self.div_required_result.config(text=f"所需本金：約 {principal:,.0f} 元")
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ----- Tab: Life-cycle -----
    def _build_tab_life(self):
        frm = self.tab_life
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=2)

        left = ttk.Frame(frm, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(1, weight=1)

        self.life_age_now = tk.IntVar(value=30)
        self.life_age_ret = tk.IntVar(value=60)
        self.life_pv = tk.DoubleVar(value=0.0)
        self.life_pmt = tk.DoubleVar(value=15000.0)
        self.life_ret = tk.DoubleVar(value=7.0)
        self.life_due = tk.BooleanVar(value=False)

        self.life_ret_years = tk.IntVar(value=30)
        self.life_ret_return = tk.DoubleVar(value=4.0)
        self.life_mode = tk.StringVar(value="annuity")  # "annuity" or "swr"
        self.life_swr = tk.DoubleVar(value=4.0)

        # Accumulation
        ttk.Label(left, text="目前年齡").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_age_now).grid(row=0, column=1, sticky="ew")
        ttk.Label(left, text="退休年齡").grid(row=1, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_age_ret).grid(row=1, column=1, sticky="ew")
        ttk.Label(left, text="初始本金 (元)").grid(row=2, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_pv).grid(row=2, column=1, sticky="ew")
        ttk.Label(left, text="每月投入 (元)").grid(row=3, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_pmt).grid(row=3, column=1, sticky="ew")
        ttk.Label(left, text="年化報酬率 (%)").grid(row=4, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_ret).grid(row=4, column=1, sticky="ew")
        ttk.Checkbutton(left, text="期初投入", variable=self.life_due).grid(row=5, column=0, columnspan=2, sticky="w")

        sep = ttk.Separator(left, orient="horizontal"); sep.grid(row=6, column=0, columnspan=2, sticky="ew", pady=6)

        # Retirement
        ttk.Label(left, text="退休年期 (年)").grid(row=7, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_ret_years).grid(row=7, column=1, sticky="ew")
        ttk.Label(left, text="退休期年化報酬率 (%)").grid(row=8, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_ret_return).grid(row=8, column=1, sticky="ew")

        mode_row = ttk.Frame(left); mode_row.grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(mode_row, text="固定年期提領 (等額)", variable=self.life_mode, value="annuity").pack(side="left")
        ttk.Radiobutton(mode_row, text="安全提領率 SWR", variable=self.life_mode, value="swr").pack(side="left")
        ttk.Label(left, text="SWR (%)").grid(row=10, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.life_swr).grid(row=10, column=1, sticky="ew")

        ttk.Button(left, text="試算 & 繪圖", command=self.on_life_calc).grid(row=11, column=0, columnspan=2, sticky="ew", pady=6)

        self.life_result = ttk.Label(left, text="", foreground="#1a7f37", wraplength=360, justify="left")
        self.life_result.grid(row=12, column=0, columnspan=2, sticky="w", pady=8)

        # Right: plots
        right = ttk.Frame(frm)
        right.grid(row=0, column=1, sticky="nsew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # Two stacked plots: accumulation, drawdown
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.life_plot_acc = PlotArea(ttk.Frame(right))
        self.life_plot_acc.fig.canvas.manager = None  # avoid warnings
        self.life_plot_acc.canvas.get_tk_widget().master.grid(row=0, column=0, sticky="nsew")

        self.life_plot_draw = PlotArea(ttk.Frame(right))
        self.life_plot_draw.fig.canvas.manager = None
        self.life_plot_draw.canvas.get_tk_widget().master.grid(row=1, column=0, sticky="nsew")

    def on_life_calc(self):
        try:
            years_acc = max(0, self.life_age_ret.get() - self.life_age_now.get())
            months_acc = years_acc * 12
            i = annual_to_monthly_rate(self.life_ret.get())
            due = self.life_due.get()

            acc_balances = simulate_growth(self.life_pv.get(), self.life_pmt.get(), i, months_acc, due)
            corpus = acc_balances[-1]

            # Retirement
            if self.life_mode.get() == "annuity":
                m = int(round(self.life_ret_years.get() * 12))
                monthly_w = monthly_withdraw_for_years(corpus, self.life_ret_return.get(), self.life_ret_years.get())
                draw_balances = simulate_drawdown(corpus, monthly_w, self.life_ret_return.get(), m)
                mode_text = f"等額提領約每月：{monthly_w:,.0f} 元，提領期 {self.life_ret_years.get()} 年"
            else:
                monthly_w = swr_monthly(corpus, self.life_swr.get())
                m = int(round(self.life_ret_years.get() * 12))
                draw_balances = simulate_drawdown(corpus, monthly_w, self.life_ret_return.get(), m)
                mode_text = f"SWR {self.life_swr.get():.2f}% 約每月：{monthly_w:,.0f} 元（實際可持續性視市場而定）"

            # Update plots
            self.life_plot_acc.plot_series(list(range(len(acc_balances))), acc_balances,
                                           "累積階段資產曲線", "月份", "總資產 (元)")
            self.life_plot_draw.plot_series(list(range(len(draw_balances))), draw_balances,
                                            "退休提領資產曲線", "月份", "剩餘資產 (元)")

            self.life_result.config(
                text=f"退休時點資產：約 {corpus:,.0f} 元；{mode_text}"
            )
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ----- Tab: Portfolio -----
    def _build_tab_port(self):
        frm = self.tab_port
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=2)

        left = ttk.Frame(frm, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(1, weight=1)

        ttk.Label(left, text="組合名稱").grid(row=0, column=0, sticky="w")
        self.port_name = tk.StringVar(value="我的ETF組合")
        ttk.Entry(left, textvariable=self.port_name).grid(row=0, column=1, sticky="ew")

        ttk.Label(left, text="初始本金 (元)").grid(row=1, column=0, sticky="w")
        self.port_pv = tk.DoubleVar(value=0.0)
        ttk.Entry(left, textvariable=self.port_pv).grid(row=1, column=1, sticky="ew")

        ttk.Label(left, text="每月投入 (元)").grid(row=2, column=0, sticky="w")
        self.port_pmt = tk.DoubleVar(value=15000.0)
        ttk.Entry(left, textvariable=self.port_pmt).grid(row=2, column=1, sticky="ew")

        ttk.Label(left, text="投資年數 (年)").grid(row=3, column=0, sticky="w")
        self.port_years = tk.IntVar(value=20)
        ttk.Entry(left, textvariable=self.port_years).grid(row=3, column=1, sticky="ew")

        # Assets grid
        assets_frame = ttk.LabelFrame(left, text="資產明細（名稱 / 權重% / 年化報酬% / 年化殖利率%）", padding=6)
        assets_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=6)
        for c in range(4):
            assets_frame.columnconfigure(c, weight=1)

        self.asset_rows: List[Tuple[tk.StringVar, tk.DoubleVar, tk.DoubleVar, tk.DoubleVar]] = []
        header = ["名稱", "權重 %", "年化報酬 %", "年化殖利率 %"]
        for idx, h in enumerate(header):
            ttk.Label(assets_frame, text=h, font=("newspaper", 9, "bold")).grid(row=0, column=idx, sticky="w")

        def add_row(name="", w=25.0, r=7.0, y=3.0):
            rname = tk.StringVar(value=name)
            rw = tk.DoubleVar(value=w)
            rr = tk.DoubleVar(value=r)
            ry = tk.DoubleVar(value=y)
            row_index = len(self.asset_rows) + 1
            ttk.Entry(assets_frame, textvariable=rname).grid(row=row_index, column=0, sticky="ew", padx=2, pady=2)
            ttk.Entry(assets_frame, textvariable=rw).grid(row=row_index, column=1, sticky="ew", padx=2, pady=2)
            ttk.Entry(assets_frame, textvariable=rr).grid(row=row_index, column=2, sticky="ew", padx=2, pady=2)
            ttk.Entry(assets_frame, textvariable=ry).grid(row=row_index, column=3, sticky="ew", padx=2, pady=2)
            self.asset_rows.append((rname, rw, rr, ry))

        # default 4 rows
        for _ in range(4):
            add_row()

        btns = ttk.Frame(left)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Button(btns, text="新增一列", command=lambda: add_row("")).pack(side="left")
        ttk.Button(btns, text="刪除最後一列", command=self.on_port_del_row).pack(side="left", padx=4)
        ttk.Button(btns, text="計算 & 繪圖", command=self.on_port_calc).pack(side="right")

        self.port_result = ttk.Label(left, text="", foreground="#1a7f37", wraplength=360, justify="left")
        self.port_result.grid(row=6, column=0, columnspan=2, sticky="w", pady=8)

        # Right plots (pie + growth)
        right = ttk.Frame(frm)
        right.grid(row=0, column=1, sticky="nsew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.port_plot_pie = PlotArea(ttk.Frame(right))
        self.port_plot_pie.canvas.get_tk_widget().master.grid(row=0, column=0, sticky="nsew")

        self.port_plot_growth = PlotArea(ttk.Frame(right))
        self.port_plot_growth.canvas.get_tk_widget().master.grid(row=1, column=0, sticky="nsew")

    def on_port_del_row(self):
        if not self.asset_rows:
            return
        # remove widgets in the last row
        # Simpler: rebuild the whole grid except last row (for brevity)
        messagebox.showinfo("提示", "為簡化程式碼，請重新開啟程式以重置列數；或覆蓋最後一列內容即可。")

    def on_port_calc(self):
        try:
            names, weights, returns, yields = [], [], [], []
            for (n_var, w_var, r_var, y_var) in self.asset_rows:
                name = n_var.get().strip() or f"資產{len(names)+1}"
                w = w_var.get()
                r = r_var.get()
                y = y_var.get()
                names.append(name); weights.append(w); returns.append(r); yields.append(y)

            total_w = sum(weights)
            if total_w <= 0:
                raise ValueError("權重總和需大於 0。")
            # normalize to 100%
            weights = [w/total_w*100.0 for w in weights]

            port_return = sum(w/100.0 * r for w, r in zip(weights, returns))
            port_yield = sum(w/100.0 * y for w, y in zip(weights, yields))

            # Pie
            self.port_plot_pie.plot_pie(names, weights, f"{self.port_name.get()} 權重分佈（正規化後）")

            # Growth using portfolio expected return
            months = max(0, int(self.port_years.get()) * 12)
            i = annual_to_monthly_rate(port_return)
            balances = simulate_growth(self.port_pv.get(), self.port_pmt.get(), i, months, False)
            xs = list(range(len(balances)))
            self.port_plot_growth.plot_series(xs, balances, "組合預期成長（以加權年化報酬為假設）", "月份", "總資產 (元)")

            corpus = balances[-1]
            monthly_div = monthly_dividend_income(corpus, port_yield)

            self.port_result.config(
                text=(f"加權年化報酬：約 {port_return:.2f}%；加權殖利率：約 {port_yield:.2f}%\n"
                      f"{self.port_years.get()} 年期末資產：約 {corpus:,.0f} 元；屆時估計月股息：約 {monthly_div:,.0f} 元")
            )
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ----- Tab: Scenarios -----
    def _build_tab_scn(self):
        frm = self.tab_scn
        frm.columnconfigure(0, weight=1)

        desc = ("情境參數提供一鍵套用到各計算頁籤的『年化報酬率』與『殖利率』預設值。\n"
                "套用後可再自行調整。")
        ttk.Label(frm, text=desc, wraplength=1000, justify="left").grid(row=0, column=0, sticky="w", padx=10, pady=6)

        grid = ttk.Frame(frm, padding=10)
        grid.grid(row=1, column=0, sticky="nsew")
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1); grid.columnconfigure(2, weight=1); grid.columnconfigure(3, weight=1)

        row = 0
        for name, p in self.scenarios.items():
            box = ttk.LabelFrame(grid, text=name, padding=8)
            box.grid(row=row//4, column=row%4, sticky="nsew", padx=6, pady=6)
            ttk.Label(box, text=f"年化報酬率：{p['return']:.1f}%").grid(row=0, column=0, sticky="w")
            ttk.Label(box, text=f"年化殖利率：{p['div_yield']:.1f}%").grid(row=1, column=0, sticky="w")
            ttk.Button(box, text="套用到輸入欄位", command=lambda v=p: self.apply_scenario(v)).grid(row=2, column=0, sticky="ew", pady=6)
            row += 1

    def apply_scenario(self, p: dict):
        # DCA
        self.dca_return.set(p["return"])
        # Goal
        self.goal_return.set(p["return"])
        # Dividend
        self.div_yield.set(p["div_yield"])
        self.div_yield2.set(p["div_yield"])
        # Life-cycle
        self.life_ret.set(p["return"])
        self.life_ret_return.set(p["return"])
        # Portfolio: apply to each row return/yield (keep weights/names)
        for (_n, _w, rr, yy) in self.asset_rows:
            rr.set(p["return"]); yy.set(p["div_yield"])
        messagebox.showinfo("完成", f"已套用情境：年化報酬 {p['return']}% / 殖利率 {p['div_yield']}%")

def main():
    app = ETFCalculatorApp()
    app.mainloop()

if __name__ == "__main__":
    main()
