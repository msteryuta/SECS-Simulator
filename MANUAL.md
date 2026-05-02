# SECS/GEM Simulator 使用手冊

> **機型支援**：TFC-6600-WB / TFC-6500-WB（Shibaura Mechatronics）  
> **協議標準**：SEMI E5 (SECS-II)、E30 (GEM)、E37 (HSMS)  
> **測試狀態**：102 unit tests — all passed

---

## 目錄

1. [環境需求 & 啟動方式](#1-環境需求--啟動方式)  
2. [視窗三欄說明](#2-視窗三欄說明)  
3. [HOST Control 左欄操作詳解](#3-host-control-左欄操作詳解)  
   - 3.1 [Machine Model — 機型選擇](#31-machine-model--機型選擇)  
   - 3.2 [Connection — 連線控制](#32-connection--連線控制)  
   - 3.3 [HOST Sends (Quick) — 快速動作](#33-host-sends-quick--快速動作)  
   - 3.4 [Remote Command S2F41](#34-remote-command-s2f41)  
   - 3.5 [Trigger EQ Event S6F11](#35-trigger-eq-event-s6f11)  
   - 3.6 [Trigger EQ Alarm S5F1](#36-trigger-eq-alarm-s5f1)  
4. [SECS Sniffer 中欄](#4-secs-sniffer-中欄)  
5. [EQ Status 右欄](#5-eq-status-右欄)  
6. [標準操作流程（Step-by-Step）](#6-標準操作流程step-by-step)  
7. [Control State 轉換邏輯](#7-control-state-轉換邏輯)  
8. [四階段通訊交握原理](#8-四階段通訊交握原理)  
9. [RCMD 完整參數說明](#9-rcmd-完整參數說明)  
10. [Collection Event (CEID) 說明](#10-collection-event-ceid-說明)  
11. [設定檔結構說明](#11-設定檔結構說明)  
12. [程式架構說明](#12-程式架構說明)  

---

## 1. 環境需求 & 啟動方式

### 需求

```
Python 3.10+
tkinter（標準函式庫，無需額外安裝）
```

### 啟動指令

```bash
# 進入專案目錄
cd SECS_Simulator/

# 方法一：互動選擇機型（彈出 Dialog）
python main.py

# 方法二：直接啟動 TFC-6600-WB
python main.py --model 6600WB

# 方法三：直接啟動 TFC-6500-WB
python main.py --model 6500WB
```

### 執行測試

```bash
cd SECS_Simulator/
python -m pytest tests/ -q
```

---

## 2. 視窗三欄說明

```
┌─────────────────────────────────────────────────────────────────────────┐
│  狀態列（連線狀態 / 機型版本）                                            │
├──────────────────┬─────────────────────────────┬────────────────────────┤
│  HOST Control    │     SECS Sniffer             │    EQ Status           │
│  （左欄）        │     （中欄）                 │    （右欄）            │
│                  │                             │                        │
│  • 機型選擇      │  藍字: Host→EQ 封包          │  • Control State       │
│  • 連線控制      │  綠字: EQ→Host 封包          │  • Process State       │
│  • 快速動作      │  灰字: 系統訊息              │  • 目前 PPID           │
│  • S2F41 RCMD   │  紅字: 錯誤訊息              │  • Stage 有無 Wafer    │
│  • S6F11 事件   │                             │  • Recent Events       │
│  • S5F1 警報    │                             │                        │
└──────────────────┴─────────────────────────────┴────────────────────────┘
```

---

## 3. HOST Control 左欄操作詳解

### 3.1 Machine Model — 機型選擇

| UI 元件 | 操作 | 效果 |
|---------|------|------|
| Model Combobox | 選擇 TFC-6600 / TFC-6500 | 即時重載對應 JSON 設定檔，RCMD / CEID / ALID 下拉清單全部更新 |

**注意**：切換機型**不需要重啟程式**，但若正在執行模擬中的 START 序列，建議等待完成後再切換。

---

### 3.2 Connection — 連線控制

#### Start Listening（綠色按鈕）

**功能**：啟動 HSMS Passive Server，開始監聽指定 Port（預設 5000）。

**實際行為**：
1. 在背景 Thread 啟動 TCP Socket，`bind()` 並 `listen(1)`
2. 狀態列顯示 `🟡 Listening on port 5000…`
3. Sniffer 顯示灰色系統訊息：`EQ passive server listening on port 5000`
4. 等待外部 HOST（EAP）以 HSMS-SS 主動連入

**注意**：GUI 的快速動作（Quick Actions）**不依賴**此伺服器運作——即使未啟動監聽，也可以在 GUI 內部直接發送訊息模擬。

#### Stop（紅色按鈕）

**功能**：停止 TCP Server，切斷現有連線（若有），釋放 Port。

---

### 3.3 HOST Sends (Quick) — 快速動作

這些按鈕模擬「HOST 主動發送」的動作，訊息直接進入 Router 處理（不走 TCP），會在 Sniffer 顯示並觸發對應 EQ 回覆。

#### S1F13  Establish Comms（建立通訊）

**功能**：HOST 向 EQ 建立 SECS 通訊連線（必須第一個執行的指令）。

**內部行為**：
- EQ 的 `handle_s1f13` 收到後，將 Control State 從 `EQ Offline` → `Attempt Online` → `Host Offline`
- EQ 回覆 `S1F14`：`COMMACK=0`（已接受）+ 機型名稱 `[MODEL, SOFTREV]`
- Sniffer：藍字送出 S1F13，緊接著綠字回覆 S1F14

**什麼時候用**：模擬開始的第一步，或重新建立通訊。

---

#### S1F17  Request Online（要求上線）

**功能**：HOST 要求 EQ 切換至 Online Remote 狀態。

**內部行為**：
- EQ 的 `handle_s1f17` 執行 `transition_control(ONLINE_REMOTE)`
- EQ 回覆 `S1F18`：`ONLACK=0`（接受）
- Control State 變為 `ONLINE REMOTE`（右欄顯示綠燈）
- **此時 S2F41 所有 Remote Command 才生效**

**ONLACK 回傳碼**：
| 碼 | 意義 |
|----|------|
| 0 | Accepted（正常接受） |
| 1 | Not Allowed（無法切換） |
| 2 | Already Online（已在線上，重複請求） |

---

#### S1F15  Request Offline（要求下線）

**功能**：HOST 要求 EQ 切換至 Host Offline 狀態。

**內部行為**：
- EQ 執行 `transition_control(HOST_OFFLINE)`
- EQ 回覆 `S1F16`：`OFLACK=0`（已確認）
- Control State 變回 `HOST OFFLINE`（橙色）
- **此後 S2F41 指令全部失效直到重新上線**

---

#### S1F1  Are You There?（通訊確認）

**功能**：HOST 確認 EQ 是否存活並在線。

**內部行為**：
- EQ 的 `handle_s1f1` 回覆 `S1F2`：`L[MODEL, SOFTREV]`（機型資訊）
- Sniffer 顯示完整的 Model / SoftRev 字串
- 不改變任何狀態

**使用時機**：檢查 EQ 是否正常運作；通訊已建立後的任何時間均可發送。

---

#### S7F19  List Recipes（查詢配方列表）

**功能**：HOST 查詢 EQ 目前儲存的所有配方（Process Program）列表。

**內部行為**：
- EQ 的 `handle_s7f19` 回傳記憶體中的 PPID 清單（預設有 `RecipeA`、`RecipeB`、`RecipeC`）
- EQ 回覆 `S7F20`：`L[A(PPID1), A(PPID2), ...]`
- 若有透過 `PPSELECT` 載入的配方，也會包含在內

---

### 3.4 Remote Command S2F41

**S2F41** 是 HOST 遠端控制 EQ 的核心指令。

#### 操作步驟

1. **RCMD Combobox**：選擇要發送的指令名稱（例如 `START`）
2. **描述欄**：自動顯示該指令的說明文字
3. **參數欄**：根據指令自動產生對應的輸入欄位
4. **▶ Send S2F41**：送出指令

#### HCACK 回傳碼（S2F42）

| 碼 | 名稱 | 說明 |
|----|------|------|
| 0 | OK | 指令已執行 |
| 1 | No Command | RCMD 名稱不存在 |
| 2 | Cannot Now | 目前狀態無法執行（如 START 時 EQ 正在執行） |
| 3 | Bad Param | 缺少必要參數 |
| 4 | Will Signal | 已接受，稍後透過 S6F11 通知完成 |
| 5 | Already | 已在目標狀態 |
| 65 | Servo OFF | 伺服電源未啟動 |
| 71 | No Map | Map 未載入 |
| 72 | Not Ready | 尚未就緒 |

#### 各 RCMD 詳細說明

##### START — 啟動自動生產

**條件**：Control State = Online Remote  
**參數**：

| 參數 | 格式 | 說明 |
|------|------|------|
| CARRIERID-L | ASCII (max 16) | 左側 Carrier ID（選填） |
| BOTTOMWAFERID-L | ASCII (max 16) | 左側底部 Wafer ID（選填） |
| CARRIERID-R | ASCII (max 16) | 右側 Carrier ID（選填，6500WB） |
| BOTTOMWAFERID-R | ASCII (max 16) | 右側底部 Wafer ID（選填，6500WB） |

**執行序列**（背景 Thread，HCACK=4 回傳後非同步進行）：

```
S2F42 HCACK=4 (立即回覆)
  ↓ 背景 Thread 啟動
CEID 140  AutorunStart      ← 自動生產啟動
CEID 259  BgStgPresenceInfo ← Bonding Stage 有 Wafer
CEID 107  BottomWaferStart  ← 底部 Wafer 開始處理
CEID 150  ProcessStart      ← 加工開始（右欄 Process State → EXECUTING）
         ↕ 等待 3 秒（模擬實際加工時間）
CEID 151  ProcessEnd        ← 加工結束
CEID 141  AutorunEnd        ← 自動生產結束（Process State → IDLE）
```

---

##### STOP — 停止自動生產

**條件**：Online Remote  
**參數**：無  
**行為**：Process State 從 `EXECUTING` 切換至 `STOPPING`，觸發 `CEID 141`（AutorunEnd）

---

##### PPSELECT — 載入配方

**條件**：Online Remote  
**參數**：

| 參數 | 格式 | 說明 |
|------|------|------|
| PPID | ASCII (max 64) | 配方名稱（必填） |

**行為**：
- 立即更新 `gem_state.ppid`
- 右欄「Recipe (PPID)」顯示新配方名稱
- 觸發 `CEID 152`（RecipeChanged）

---

##### GOLOCAL — 切換至 Local 模式

**條件**：Online Remote  
**參數**：無  
**行為**：Control State 切換至 `ONLINE LOCAL`，此後大部分 RCMD 無效

---

##### GOREMOTE — 切換至 Remote 模式

**條件**：Online Local  
**參數**：無  
**行為**：Control State 切換至 `ONLINE REMOTE`，恢復 RCMD 控制權

---

##### BOTTOMSTAGEGOREADY — Bonding Stage 就定位

**條件**：Online Remote  
**參數**：`DEVICESIDE`（1=左側, 2=右側）  
**行為**：模擬機械臂將 Bonding Stage 移至接收位置，觸發 `CEID 142`（BottomStgReady）

---

##### BOTTOMMAPREAD — 通知底部 Map

**條件**：Online Remote  
**參數**：`DEVICESIDE`（1/2）、`MAPFILENAME`（map 檔案路徑，max 40）  
**行為**：通知 EQ 底部 Wafer 的 Die Map 檔名（EQ 載入 map 資料）

---

##### BOTTOMWAFERLOADCOMPLETE — 底部 Wafer 放置完成

**條件**：Online Remote  
**參數**：`DEVICESIDE`、`CARRIERID`、`BOTTOMWAFERID`、`LOTID`、`SLOTID`  
**行為**：通知 EQ Wafer 已放置於 Bonding Stage，觸發 `CEID 259`（BgStgPresenceInfo）

---

##### BOTTOMWAFERUNLOADCOMPLETE — 底部 Wafer 卸載完成

**條件**：Online Remote  
**參數**：`DEVICESIDE`  
**行為**：觸發 `CEID 260`（BgStageUnloadMove）+ `CEID 262`（LogStored）

---

##### WAFERSTAGEGOREADY — Wafer Stage 就定位

**條件**：Online Remote  
**參數**：無  
**行為**：模擬頂部 Wafer Stage 移至接收位置，觸發 `CEID 144`（WfStgReady）

---

##### TOPMAPREAD — 通知頂部 Map

**條件**：Online Remote  
**參數**：`MAPFILENAME`（map 檔案路徑，max 40）  
**行為**：通知 EQ 頂部 Wafer 的 Die Map 檔名

---

##### TOPWAFERLOADCOMPLETE — 頂部 Wafer 放置完成

**條件**：Online Remote  
**參數**：`CARRIERID`、`TOPWAFERID`、`LOTID`、`SLOTID`  
**行為**：通知 EQ 頂部 Wafer 放置完成，Expand Clamp 關閉

---

##### TOPWAFERUNLOADCOMPLETE — 頂部 Wafer 卸載完成

**條件**：Online Remote  
**參數**：無  
**行為**：觸發 `CEID 146`（WfUnloadFinish）

---

##### UPLOAD_MAP — 上傳 Die-Bond Map

**條件**：Online Remote  
**參數**：`WAFERID`（目標 Wafer ID，max 16）  
**行為**：EQ 將指定 Wafer 的 Map 資料打包，觸發 `CEID 263`（UploadMap）

---

##### AOISTOP — 停止 AOI

**條件**：Online Remote  
**參數**：無  
**行為**：停止自動光學檢測（Automated Optical Inspection）動作

---

##### FLUXMON_X / FLUXMON_Y（6500WB 專屬）

**條件**：Online Remote，且配方類型為 Flux Monitor  
**參數**：`DEVICESIDE`（1=左, 2=右）  
**行為**：啟動 Flux 薄膜監控功能（X 或 Y 方向），觸發 `CEID 130`（FluxFinishEvent）  
**HCACK 77**：目前配方不是 Flux Monitor 類型時拒絕

---

##### EMBOSSREADREQUEST（6500WB 專屬）

**條件**：Online Remote  
**參數**：`DEVICESIDE`、`REELNUMBER`（0=無 1=Reel1 2=Reel2 3=1&2 4=Reel3 …）  
**行為**：請求 EQ 讀取 Emboss Tape 的 Barcode，觸發 `CEID 162`  
**HCACK 74**：Tape Set Sensor 未感應到 Tape

---

##### EMBOSSMAPVERIFYOK / EMBOSSMAPVERIFYNG（6500WB 專屬）

**條件**：Online Remote  
**參數**：`DEVICESIDE`、`REELNO`、`MAPFILENAME`（僅 OK 需要）  
**行為**：HOST 驗證 Emboss Map 後通知 EQ 結果（OK=放行 / NG=停止）

---

##### CURRENTREELREQUEST（6500WB 專屬）

**條件**：Online Remote  
**參數**：`DEVICESIDE`、`REELNO`  
**行為**：請求 EQ 切換到指定 Reel  
**HCACK 70**：Auto Running 中拒絕；**HCACK 75**：Reel 未驗證

---

##### INPRINTMON（6500WB 專屬）

**條件**：Online Remote，且配方類型為 Inprint Monitor  
**參數**：無  
**行為**：啟動 Inprint 紋路監控，完成後觸發 `CEID 155`（InprintMonitorFinished）

---

### 3.5 Trigger EQ Event S6F11

**功能**：手動讓 EQ 主動發送一個 Collection Event（不透過 RCMD）。

**操作**：
1. 從 CEID Combobox 選擇要觸發的事件（格式：`150: ProcessStart`）
2. 點擊「Fire Event (S6F11)」

**內部行為**：
- 呼叫 `send_s6f11(router, ceid)`
- 從設定檔讀取該 CEID 的 `rptid` 和 `vids`（關聯的 SVID 清單）
- 從 `gem_state` 讀取各 SVID 的目前值，組成 Report
- 透過 `router.send_unsolicited(6, 11, body)` 送出
- Sniffer 顯示綠字 S6F11
- 右欄 EQ Status 的 Recent Events 記錄此事件
- **不會自動等待 S6F12 回覆**（模擬器的 HOST 面板收到後會自動回覆 S6F12）

**適用場景**：測試外部 HOST 的 S6F11 接收邏輯時，手動觸發特定事件。

---

### 3.6 Trigger EQ Alarm S5F1

**功能**：手動讓 EQ 主動發送一筆 Alarm Report。

**操作**：
1. 從 ALID Combobox 選擇要觸發的警報（格式：`1001: ServoPowerOff`）
2. 點擊「Set Alarm」（警報發生）或「Clear Alarm」（警報解除）

**內部行為（Set Alarm）**：
- 從設定檔讀取 ALID 的 `category`、`text`
- 組建 `ALCD = 0x80 | category`（bit7=1 表示警報發生）
- S5F1 body：`L[ALCD, ALID, ALTX]`
- 發送至 HOST，Sniffer 顯示綠字 S5F1

**內部行為（Clear Alarm）**：
- `ALCD = category`（bit7=0 表示警報解除）
- 其餘相同

**ALID 說明**（預設已定義）：

| ALID | 名稱 | Category | 說明 |
|------|------|----------|------|
| 1001 | ServoPowerOff | 2 | 伺服電源意外關閉 |
| 1002 | VacuumError | 2 | 真空系統異常 |
| 1003 | TempError | 4 | 製程溫度超出範圍 |
| 1004 | WaferMisalign | 3 | Wafer 位置偏移 |
| 1005 | EmergencyStop | 1 | 硬體緊急停止 |
| 1006 | EmbossError | 2 | Emboss 裝置異常（6500WB） |
| 1007 | FluxMonitorErr | 3 | Flux Monitor 異常（6500WB） |

---

## 4. SECS Sniffer 中欄

Sniffer 是通訊封包的即時監控視窗，採用色彩編碼：

| 顏色 | 方向 | 說明 |
|------|------|------|
| 藍色 | Host → EQ | HOST 發送的訊息 |
| 綠色 | EQ → Host | EQ 發送或回覆的訊息 |
| 灰色 | System | 連線狀態、系統資訊 |
| 紅色 | Error | 錯誤訊息、Bind 失敗 |

**顯示內容**：時間戳記、方向標記、訊息名稱、重要欄位值（如 HCACK、CEID）

---

## 5. EQ Status 右欄

| 區塊 | 說明 |
|------|------|
| Control State | 當前 GEM Control State，附顏色指示燈 |
| Process State | IDLE / SETUP / EXECUTING / PAUSE / ALARM / STOPPING |
| Recipe (PPID) | 透過 PPSELECT 載入的配方名稱 |
| Stage Presence | BG Stage L / R / Wafer Stage 有無 Wafer |
| Recent Events | 即時記錄所有 CEID 事件與 Alarm 發生歷程 |

**Control State 顏色**：
- 紅：EQ Offline
- 黃：Attempt Online / Host Offline
- 淺綠：Online Local
- 深綠：Online Remote

---

## 6. 標準操作流程（Step-by-Step）

### 6.1 基本通訊建立

```
1. python main.py --model 6600WB
2. 左欄 → Click「Start Listening」
3. 左欄 → Click「S1F13 Establish Comms」
   → 右欄 Control State 變成 HOST OFFLINE（橙色）
4. 左欄 → Click「S1F17 Request Online」
   → 右欄 Control State 變成 ONLINE REMOTE（深綠）
```

### 6.2 執行一次完整 START 生產循環

```
5. 左欄 → RCMD 選「START」
6. 填入 CARRIERID-L（如：CARRIER001）
7. Click「▶ Send S2F41」
   → Sniffer: 藍字 S2F41 (START)
   → Sniffer: 綠字 S2F42 (HCACK=4)     ← 立即回覆，非同步進行
   → 右欄: Process State → EXECUTING（綠燈）
   → Sniffer: 綠字 S6F11 CEID=140      ← AutorunStart
   → Sniffer: 綠字 S6F11 CEID=259      ← BgStgPresenceInfo
   → Sniffer: 綠字 S6F11 CEID=107      ← BottomWaferStart
   → Sniffer: 綠字 S6F11 CEID=150      ← ProcessStart
   （等待 3 秒模擬加工）
   → Sniffer: 綠字 S6F11 CEID=151      ← ProcessEnd
   → Sniffer: 綠字 S6F11 CEID=141      ← AutorunEnd
   → 右欄: Process State → IDLE
```

### 6.3 切換配方

```
左欄 → RCMD 選「PPSELECT」
填入 PPID（如：RecipeA）
Click「▶ Send S2F41」
  → 右欄 Recipe 顯示 RecipeA
  → Sniffer: S6F11 CEID=152 (RecipeChanged)
```

### 6.4 手動觸發警報

```
左欄 → ALID 選「1001: ServoPowerOff」
Click「Set Alarm」
  → Sniffer: 綠字 S5F1 (Alarm SET)
  → 右欄 Recent Events 記錄

Click「Clear Alarm」
  → Sniffer: 綠字 S5F1 (Alarm CLEARED)
```

---

## 7. Control State 轉換邏輯

```
EQ Offline
    │ S1F13（Establish Comms）
    ↓
Host Offline  ←──────────────────── S1F15（Request Offline）
    │ S1F17（Request Online）             ↑
    ↓                                    │
Online Remote ────────────────────── GOREMOTE
    │ GOLOCAL                            │
    ↓                                    │
Online Local ──────────────────────────┘
```

**各狀態可用的 RCMD**：

| 狀態 | 可用 RCMD |
|------|-----------|
| Online Remote | 全部（含 START、STOP、PPSELECT 等） |
| Online Local | 僅 GOREMOTE |
| Host Offline / EQ Offline | 無 RCMD 可用 |

---

## 8. 四階段通訊交握原理

以 `START` 指令為例：

```
HOST                                        EQ
 │                                           │
 │─── S2F41 [START, CARRIERID-L=...] ───────→│  ① HOST 下達指令
 │                                           │
 │←── S2F42 [HCACK=4] ──────────────────────│  ② EQ 立即確認（非同步將信號）
 │                                           │
 │          (EQ 背景執行硬體動作)            │
 │                                           │  ③ EQ 內部執行
 │←── S6F11 [CEID=150, ProcessStart] ───────│     (3 秒後) EQ 主動回報事件
 │                                           │
 │─── S6F12 [ACKC6=0] ──────────────────────→│  ④ HOST 確認收到事件
 │                                           │
```

**要點**：
- 階段 ① ② 是同步的（Send → Reply）
- 階段 ③ ④ 是非同步的（EQ 自行決定時機發送 S6F11）
- 模擬器的 GUI HOST 面板收到 S6F11 後**自動**回覆 S6F12

---

## 9. RCMD 完整參數說明

### 6600WB 支援 RCMD（17 個）

| RCMD | 必填參數 | 選填參數 | HCACK 錯誤 |
|------|---------|---------|-----------|
| START | — | CARRIERID-L, BOTTOMWAFERID-L | 65:ServoOFF, 72:NotReady |
| STOP | — | — | — |
| PPSELECT | PPID | — | — |
| GOLOCAL | — | — | — |
| GOREMOTE | — | — | — |
| PMSTART | DEVICESIDE | — | 77:WrongRecipeType |
| BOTTOMSTAGEGOREADY | DEVICESIDE | — | 65:ServoOFF |
| BOTTOMMAPREAD | DEVICESIDE, MAPFILENAME | — | 67:NoMap, 68:ConvertFail |
| BOTTOMWAFERLOADCOMPLETE | DEVICESIDE | CARRIERID, BOTTOMWAFERID, LOTID, SLOTID | 71:NoMap |
| BOTTOMWAFERUNLOADCOMPLETE | DEVICESIDE | — | — |
| WAFERSTAGEGOREADY | — | — | 65:ServoOFF, 69:AutoRunning |
| TOPMAPREAD | MAPFILENAME | — | 67:NoMap, 68:ConvertFail |
| TOPWAFERUNLOADREQUEST | — | — | 65:ServoOFF, 69:AutoRunning |
| TOPWAFERLOADCOMPLETE | — | CARRIERID, TOPWAFERID, LOTID, SLOTID | 65:ServoOFF, 71:NoMap, 73:NotReady |
| TOPWAFERUNLOADCOMPLETE | — | — | — |
| AOISTOP | — | — | — |
| UPLOAD_MAP | WAFERID | — | 71:NoMap, 80:WaferIDNotFound |

### 6500WB 額外 RCMD（+8 個）

| RCMD | 必填參數 | HCACK 錯誤 |
|------|---------|-----------|
| FLUXMON_X | DEVICESIDE | 77:WrongRecipeType |
| FLUXMON_Y | DEVICESIDE | 77:WrongRecipeType |
| EMBOSSREADREQUEST | DEVICESIDE, REELNUMBER | 74:TapeSensorOFF |
| EMBOSSMAPVERIFYOK | DEVICESIDE, REELNO, MAPFILENAME | 67:NoMap, 68:ConvertFail |
| EMBOSSMAPVERIFYNG | DEVICESIDE, REELNO | — |
| CURRENTREELREQUEST | DEVICESIDE, REELNO | 70:AutoRunning, 75:NotVerified |
| TOPWAFERLOADCOMPLETE2 | — | 65:ServoOFF, 71:NoMap, 73:NotReady |
| INPRINTMON | — | 77:WrongRecipeType |

---

## 10. Collection Event (CEID) 說明

### GEM 標準 CEID（兩機型共用）

| CEID | 名稱 | 觸發時機 |
|------|------|---------|
| 1 | Online:Local | Control State 切換至 Online Local |
| 2 | Online:Remote | Control State 切換至 Online Remote |
| 3 | HostOffline | Control State 切換至 Host Offline |
| 4 | EquipmentOffline | Control State 切換至 EQ Offline |

### 主要 Equipment CEID

| CEID | 名稱 | 觸發時機 | 關聯 SVID |
|------|------|---------|----------|
| 107 | BottomWaferStart | 底部 Wafer 開始處理 | 500,551,568,567,569 |
| 140 | AutorunStart | 自動生產啟動 | — |
| 141 | AutorunEnd | 自動生產結束 | — |
| 142 | BottomStgReady | Bonding Stage 就定位 | 500 |
| 144 | WfStgReady | Wafer Stage 就定位 | — |
| 150 | ProcessStart | 加工開始 | 500,568,567,569 |
| 151 | ProcessEnd | 加工結束 | 500,568,567,569 |
| 152 | RecipeChanged | 配方切換完成 | 970 |
| 180 | ServoON | Servo 電源 ON | — |
| 181 | ServoOFF | Servo 電源 OFF | — |
| 259 | BgStgPresenceInfo | START 後 BgStage 存在狀態 | 500,931,932 |

### 6500WB 專屬 CEID

| CEID | 名稱 | 說明 |
|------|------|------|
| 134 | LineScanStart | 線掃描開始 |
| 135 | LineScanEnd | 線掃描結束 |
| 155 | InprintMonitorFinished | Inprint Monitor 完成 |
| 160 | EmbossIsSettled | Emboss Tape 已放置於 Stage |
| 161 | EmbossRemoved | Emboss Tape 已取出 |
| 162 | EmbossBarcodeRead | Emboss Barcode 讀取完成 |
| 164 | OneReelIsFinished | 單 Reel 用盡 |
| 165 | AllReelIsFinished | 全部 Reel 用盡 |
| 166 | CurrentReelChanged | 當前 Reel 切換 |
| 167 | EmbossCoverOpen | Emboss Cover 開啟 |
| 168 | EmbossCoverClose | Emboss Cover 關閉 |

---

## 11. 設定檔結構說明

```
config/
├── 6600WB_eq_constants.json   ← TFC-6600 常數、CEID、ALID、SVID
├── 6600WB_s2f41_cmds.json    ← TFC-6600 RCMD 定義
├── 6500WB_eq_constants.json   ← TFC-6500 常數（含 Emboss/LineScan 事件）
└── 6500WB_s2f41_cmds.json    ← TFC-6500 RCMD（含 FLUXMON/EMBOSS 系列）
```

### eq_constants.json 欄位說明

```json
{
  "DEVICE_ID": 1,            // HSMS Device ID
  "MODEL": "TFC-6600",       // 機型名稱（顯示於標題列）
  "SOFTREV": "6.3.100",      // 軟體版本
  "HSMS": {
    "port": 5000,            // TCP 監聽 Port
    "T3": 45                 // Reply Timeout（秒）
  },
  "CEID": {
    "150": {
      "name": "ProcessStart",
      "desc": "加工開始",
      "rptid": 150,          // Report ID（S6F11 使用）
      "vids": [500, 568]     // 隨 S6F11 一起回報的 SVID 清單
    }
  },
  "ALID": {
    "1001": {
      "name": "ServoPowerOff",
      "category": 2,         // 警報類別（1=嚴重 2=警告 3=注意 4=資訊）
      "text": "Servo Power Off"
    }
  },
  "SVID": {
    "500": {
      "name": "_BottomWaferID",
      "format": "ASCII",
      "desc": "目前處理中的底部 Wafer ID"
    }
  }
}
```

### s2f41_cmds.json 欄位說明

```json
{
  "START": {
    "desc": "啟動自動生產循環",
    "params": {
      "CARRIERID-L": {
        "format": "ASCII",
        "max_len": 16,
        "required": false    // true=必填，false=選填
      }
    },
    "hcack_errors": {
      "65": "Servo OFF"      // 自訂錯誤碼說明
    },
    "triggers_events": [140, 259, 107, 150, 151, 141],  // 觸發的 CEID 序列
    "requires_state": "ONLINE_REMOTE"
  }
}
```

---

## 12. 程式架構說明

```
SECS_Simulator/
│
├── main.py              # 進入點：載入設定、綁定元件、啟動 GUI
│
├── config/              # 設定層：機台規格 JSON（改機型只改這裡）
│   ├── 6600WB_eq_constants.json
│   ├── 6600WB_s2f41_cmds.json
│   ├── 6500WB_eq_constants.json
│   └── 6500WB_s2f41_cmds.json
│
├── core/                # 核心層：寫好一次、不需改動
│   ├── secs_codec.py    # SECS-II 編解碼（SecsItem、encode/decode）
│   ├── gem_state.py     # GEM 狀態機（Control/Process State + SVID）
│   ├── hsms_server.py   # HSMS TCP 伺服器（Socket、訊框、控制訊息）
│   └── router.py        # 訊息路由器 + Pub/Sub 事件匯流排
│
├── handlers/            # 擴充層：新增指令只在這裡加檔案
│   ├── s1_handler.py    # Stream 1: S1F1/13/15/17
│   ├── s2_handler.py    # Stream 2: S2F41（RCMD）+ S2F31/33/35/37
│   ├── s5_handler.py    # Stream 5: S5F1（Alarm）+ S5F3
│   ├── s6_handler.py    # Stream 6: S6F11（Event Report）
│   └── s7_handler.py    # Stream 7: S7F17/19/25（Recipe）
│
├── gui/                 # 視覺層：事件驅動，透過 Pub/Sub 更新
│   ├── main_window.py   # 主視窗（三欄佈局 + HOST 控制面板）
│   ├── event_logger.py  # Sniffer 元件（色彩編碼、執行緒安全）
│   └── eq_panel.py      # EQ 狀態面板（Control/Process State 燈）
│
└── tests/               # 測試層：102 unit tests
    ├── test_secs_codec.py
    ├── test_gem_state.py
    ├── test_router.py
    ├── test_s1_handler.py
    ├── test_s2_handler.py
    └── test_s6_handler.py
```

### 核心設計模式

| 模式 | 位置 | 說明 |
|------|------|------|
| Router Pattern | `core/router.py` | `{(S,F): handler}` 字典取代 if-else 鏈 |
| Pub/Sub | `core/router.py` | 核心層發布事件，GUI 層訂閱更新，兩者完全解耦 |
| State Machine | `core/gem_state.py` | 驗證狀態轉換合法性，拒絕非法跳轉 |
| Config-Driven | `config/*.json` | 所有機台規格外部化，零程式碼切換機型 |
| Thread-Safe Queue | `gui/event_logger.py` | 背景 Thread 透過 Queue + `after()` 更新 UI |

---

*最後更新：2026-04-17*
