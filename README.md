
# ETF 存股計畫 — GUI 計算器

這個 Python 應用以 **Tkinter + Matplotlib** 建立多頁籤圖形化介面，提供：
- 定期定額試算（含初始本金、期初/期末投入）
- 目標反推每月投入金額
- 股息試算 & 目標月領息反推所需本金
- 生命週期試算：累積→退休提領（固定年期或 SWR 安全提領率）
- 投資組合試算：輸入多個 ETF 的權重、期望年化報酬與殖利率，估算加權報酬、加權殖利率、期末資產與月股息，並繪製權重圓餅圖 + 成長曲線
- 情境參數（較差/穩定/歷史/較佳）一鍵套用

## 安裝與執行
```bash
python3 -m venv venv
source venv/bin/activate  # Windows 使用 venv\Scripts\activate
pip install -r requirements.txt
python etf_saver_gui.py
```

> 注意：此工具使用年化報酬轉為月複利 i = (1+r)^(1/12) - 1。殖利率與報酬率皆以年化百分比輸入。

## 主要金融公式（月複利；期末投入為預設）
- **未來值（定期定額）**：FV_series = PMT * ((1+i)^n - 1)/i；期初投入乘上 (1+i)
- **含初始本金**：FV = PV*(1+i)^n + FV_series
- **反推每月投入**：PMT = (FV_target - PV*(1+i)^n) / factor，其中 factor = ((1+i)^n - 1)/i * (1+i if due else 1)
- **股息月收入**：income = principal * dividend_yield / 12
- **領息目標所需本金**：principal = target_monthly * 12 / dividend_yield
- **退休固定年期提領**：monthly = corpus * j / (1 - (1+j)^(-m))，j 為月報酬，m 為月數
- **SWR 安全提領率（月）**：monthly = corpus * swr / 12

## 免責聲明
上述試算基於使用者輸入與簡化假設，**不代表未來績效或保證**。請依個人風險承受度調整。
